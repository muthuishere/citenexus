//! Lance store — the Rust mirror of Python's `LanceVectorStore` (spec §6b,
//! SPEC-PORTS-v1 §3.4 item 1).
//!
//! One Lance database per leaf partition, one table (`evidence_units`), rows
//! keyed by `eu_id`. Semantics match `src/citenexus/storage/lance_store.py`
//! exactly:
//!
//! - `upsert` — merge-insert on `eu_id` (idempotent); the table is created on
//!   the first upsert. Empty input is a no-op.
//! - `search` — nearest rows to a query vector, each row carrying `_distance`;
//!   `[]` when the leaf has no table yet.
//! - `scan` — every row (optionally truncated), `[]` when no table yet.
//! - `drop_table` — the leaf becomes empty; dropping a missing table is a no-op.
//!
//! The boundary is JSON: rows go in as a JSON array of objects and come back
//! the same way. Supported column types are what Evidence Unit rows use —
//! strings, integers, floats, booleans, and the `vector` column (a JSON array
//! of numbers, stored as `FixedSizeList<Float32>` like Python lancedb does).
//! lancedb's Rust API is async, so the store holds a small private tokio
//! runtime and blocks on it — callers (and the C ABI) stay synchronous.

use std::collections::BTreeMap;
use std::sync::Arc;

use arrow_array::builder::{BooleanBuilder, Float64Builder, Int64Builder, StringBuilder};
use arrow_array::{ArrayRef, FixedSizeListArray, Float32Array, RecordBatch, RecordBatchIterator};
use arrow_schema::{DataType, Field, Schema};
use futures::TryStreamExt;
use lancedb::query::{ExecutableQuery, QueryBase};
use lancedb::Connection;
use serde_json::Value;

/// The single table each leaf database holds (same name as Python's
/// `LanceVectorStore.TABLE`).
pub const TABLE: &str = "evidence_units";

/// storage_options keys for S3/MinIO: endpoint, allow_http, access_key_id,
/// secret_access_key, region — passed straight through to lancedb.
pub type StorageOptions = BTreeMap<String, String>;

/// The vector index for a single leaf partition (Rust twin of
/// `LanceVectorStore`).
pub struct LanceStore {
    runtime: tokio::runtime::Runtime,
    db: Connection,
}

impl LanceStore {
    /// Connect to a leaf database at `uri` (local path or `s3://…`).
    pub fn open(uri: &str, storage_options: &StorageOptions) -> Result<Self, String> {
        let runtime = tokio::runtime::Builder::new_multi_thread()
            .enable_all()
            .build()
            .map_err(|e| format!("tokio runtime: {e}"))?;
        let db = runtime.block_on(async {
            let mut builder = lancedb::connect(uri);
            for (key, value) in storage_options {
                builder = builder.storage_option(key, value);
            }
            builder.execute().await.map_err(|e| e.to_string())
        })?;
        Ok(Self { runtime, db })
    }

    fn table_exists(&self) -> Result<bool, String> {
        self.runtime.block_on(async {
            let names = self
                .db
                .table_names()
                .execute()
                .await
                .map_err(|e| e.to_string())?;
            Ok(names.iter().any(|n| n == TABLE))
        })
    }

    /// Insert or update rows keyed by `eu_id` (idempotent). `rows` must be a
    /// JSON array of objects; the table is created on first use.
    pub fn upsert(&self, rows: &Value) -> Result<(), String> {
        let rows = rows
            .as_array()
            .ok_or_else(|| "rows must be a JSON array".to_string())?;
        if rows.is_empty() {
            return Ok(());
        }
        let batch = rows_to_batch(rows)?;
        let schema = batch.schema();
        let exists = self.table_exists()?;
        self.runtime.block_on(async {
            let reader = RecordBatchIterator::new(vec![Ok(batch)], schema);
            if exists {
                let table = self
                    .db
                    .open_table(TABLE)
                    .execute()
                    .await
                    .map_err(|e| e.to_string())?;
                let mut merge = table.merge_insert(&["eu_id"]);
                merge.when_matched_update_all(None);
                merge.when_not_matched_insert_all();
                merge
                    .execute(Box::new(reader))
                    .await
                    .map_err(|e| e.to_string())?;
            } else {
                let reader: Box<dyn arrow_array::RecordBatchReader + Send> = Box::new(reader);
                self.db
                    .create_table(TABLE, reader)
                    .execute()
                    .await
                    .map_err(|e| e.to_string())?;
            }
            Ok(())
        })
    }

    /// Nearest rows to `vector` (each with `_distance`); `[]` when the leaf
    /// has no table yet.
    pub fn search(&self, vector: &[f32], limit: usize) -> Result<Value, String> {
        if !self.table_exists()? {
            return Ok(Value::Array(vec![]));
        }
        let batches = self.runtime.block_on(async {
            let table = self
                .db
                .open_table(TABLE)
                .execute()
                .await
                .map_err(|e| e.to_string())?;
            let stream = table
                .query()
                .nearest_to(vector)
                .map_err(|e| e.to_string())?
                .limit(limit)
                .execute()
                .await
                .map_err(|e| e.to_string())?;
            stream
                .try_collect::<Vec<RecordBatch>>()
                .await
                .map_err(|e| e.to_string())
        })?;
        batches_to_json(&batches)
    }

    /// All rows in this leaf (optionally truncated to `limit`) — the corpus
    /// for lexical/structure retrievers. `[]` when the leaf has no table yet.
    pub fn scan(&self, limit: Option<usize>) -> Result<Value, String> {
        if !self.table_exists()? {
            return Ok(Value::Array(vec![]));
        }
        let batches = self.runtime.block_on(async {
            let table = self
                .db
                .open_table(TABLE)
                .execute()
                .await
                .map_err(|e| e.to_string())?;
            let mut query = table.query();
            if let Some(n) = limit {
                query = query.limit(n);
            }
            let stream = query.execute().await.map_err(|e| e.to_string())?;
            stream
                .try_collect::<Vec<RecordBatch>>()
                .await
                .map_err(|e| e.to_string())
        })?;
        batches_to_json(&batches)
    }

    /// Drop this leaf's table (the leaf becomes empty). No-op when absent.
    pub fn drop_table(&self) -> Result<(), String> {
        if !self.table_exists()? {
            return Ok(());
        }
        self.runtime.block_on(async {
            self.db
                .drop_table(TABLE, &[])
                .await
                .map_err(|e| e.to_string())
        })
    }
}

/// What a JSON column holds, decided by scanning every row's value.
#[derive(Clone, Copy, PartialEq)]
enum ColumnKind {
    Utf8,
    Int64,
    Float64,
    Boolean,
    Vector,
}

fn classify(key: &str, rows: &[Value]) -> Result<ColumnKind, String> {
    let mut kind: Option<ColumnKind> = None;
    for row in rows {
        let value = row.get(key).unwrap_or(&Value::Null);
        let this = match value {
            Value::Null => continue,
            Value::String(_) => ColumnKind::Utf8,
            Value::Bool(_) => ColumnKind::Boolean,
            Value::Number(n) if n.is_i64() || n.is_u64() => ColumnKind::Int64,
            Value::Number(_) => ColumnKind::Float64,
            Value::Array(_) if key == "vector" => ColumnKind::Vector,
            other => {
                return Err(format!(
                    "column {key:?}: unsupported JSON value {other} (rows carry \
                     strings, numbers, booleans, and a numeric \"vector\" array)"
                ))
            }
        };
        kind = Some(match (kind, this) {
            (None, k) => k,
            // Any float promotes an integer column.
            (Some(ColumnKind::Int64), ColumnKind::Float64)
            | (Some(ColumnKind::Float64), ColumnKind::Int64) => ColumnKind::Float64,
            (Some(prev), k) if prev == k => k,
            (Some(_), _) => return Err(format!("column {key:?}: mixed JSON types")),
        });
    }
    // An all-null column stores as nullable Utf8 (matches pyarrow's fallback).
    Ok(kind.unwrap_or(ColumnKind::Utf8))
}

fn vector_dim(rows: &[Value]) -> Result<i32, String> {
    let first = rows
        .iter()
        .find_map(|r| r.get("vector").and_then(Value::as_array))
        .ok_or_else(|| "vector column has no array value".to_string())?;
    i32::try_from(first.len()).map_err(|_| "vector too long".to_string())
}

fn f32_of(value: &Value) -> Result<f32, String> {
    value
        .as_f64()
        .map(|f| f as f32)
        .ok_or_else(|| format!("vector element is not a number: {value}"))
}

/// Build one Arrow `RecordBatch` from a JSON array of row objects. Columns are
/// the first row's keys (sorted); every row must use the same keys.
fn rows_to_batch(rows: &[Value]) -> Result<RecordBatch, String> {
    let first = rows[0]
        .as_object()
        .ok_or_else(|| "each row must be a JSON object".to_string())?;
    let keys: Vec<String> = {
        let mut ks: Vec<String> = first.keys().cloned().collect();
        ks.sort();
        ks
    };
    for row in rows {
        let obj = row
            .as_object()
            .ok_or_else(|| "each row must be a JSON object".to_string())?;
        if obj.len() != keys.len() || !keys.iter().all(|k| obj.contains_key(k)) {
            return Err("all rows must have the same keys".to_string());
        }
    }

    let mut fields: Vec<Field> = Vec::with_capacity(keys.len());
    let mut arrays: Vec<ArrayRef> = Vec::with_capacity(keys.len());
    for key in &keys {
        let (field, array) = build_column(key, rows)?;
        fields.push(field);
        arrays.push(array);
    }
    let schema = Arc::new(Schema::new(fields));
    RecordBatch::try_new(schema, arrays).map_err(|e| e.to_string())
}

fn build_column(key: &str, rows: &[Value]) -> Result<(Field, ArrayRef), String> {
    let kind = classify(key, rows)?;
    let values = rows.iter().map(|r| r.get(key).unwrap_or(&Value::Null));
    match kind {
        ColumnKind::Utf8 => {
            let mut b = StringBuilder::new();
            for v in values {
                match v {
                    Value::String(s) => b.append_value(s),
                    _ => b.append_null(),
                }
            }
            Ok((
                Field::new(key, DataType::Utf8, true),
                Arc::new(b.finish()) as ArrayRef,
            ))
        }
        ColumnKind::Int64 => {
            let mut b = Int64Builder::new();
            for v in values {
                match v.as_i64() {
                    Some(i) => b.append_value(i),
                    None => b.append_null(),
                }
            }
            Ok((
                Field::new(key, DataType::Int64, true),
                Arc::new(b.finish()) as ArrayRef,
            ))
        }
        ColumnKind::Float64 => {
            let mut b = Float64Builder::new();
            for v in values {
                match v.as_f64() {
                    Some(f) => b.append_value(f),
                    None => b.append_null(),
                }
            }
            Ok((
                Field::new(key, DataType::Float64, true),
                Arc::new(b.finish()) as ArrayRef,
            ))
        }
        ColumnKind::Boolean => {
            let mut b = BooleanBuilder::new();
            for v in values {
                match v.as_bool() {
                    Some(x) => b.append_value(x),
                    None => b.append_null(),
                }
            }
            Ok((
                Field::new(key, DataType::Boolean, true),
                Arc::new(b.finish()) as ArrayRef,
            ))
        }
        ColumnKind::Vector => {
            let dim = vector_dim(rows)?;
            let mut flat: Vec<f32> = Vec::with_capacity(rows.len() * dim as usize);
            for v in values {
                let arr = v
                    .as_array()
                    .ok_or_else(|| "vector column has a non-array value".to_string())?;
                if arr.len() != dim as usize {
                    return Err(format!(
                        "vector length mismatch: expected {dim}, got {}",
                        arr.len()
                    ));
                }
                for element in arr {
                    flat.push(f32_of(element)?);
                }
            }
            let item = Arc::new(Field::new("item", DataType::Float32, true));
            let list = FixedSizeListArray::new(
                item.clone(),
                dim,
                Arc::new(Float32Array::from(flat)),
                None,
            );
            Ok((
                Field::new(key, DataType::FixedSizeList(item, dim), true),
                Arc::new(list) as ArrayRef,
            ))
        }
    }
}

/// Render record batches as a JSON array of row objects (nulls explicit, so
/// the shape matches Python's `to_pylist()`).
fn batches_to_json(batches: &[RecordBatch]) -> Result<Value, String> {
    let mut writer = arrow_json::WriterBuilder::new()
        .with_explicit_nulls(true)
        .build::<_, arrow_json::writer::JsonArray>(Vec::new());
    writer
        .write_batches(&batches.iter().collect::<Vec<_>>())
        .map_err(|e| e.to_string())?;
    writer.finish().map_err(|e| e.to_string())?;
    let bytes = writer.into_inner();
    if bytes.is_empty() {
        return Ok(Value::Array(vec![]));
    }
    serde_json::from_slice(&bytes).map_err(|e| e.to_string())
}
