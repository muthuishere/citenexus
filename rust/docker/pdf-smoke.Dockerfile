# Linux smoke test for the PDF core (ADR-0017 "Runtime").
#
# glibc (Debian bookworm), a PINNED pdfium-binaries release verified by
# sha256, the core built with --features pdf, then the Rust PDF tests and the
# Go ffi PDF tests run against PDFIUM_DYNAMIC_LIB_PATH. It also prints the
# measured libpdfium.so size and the glibc floor of both shared objects.
#
#   docker build --platform linux/amd64 -f rust/docker/pdf-smoke.Dockerfile -t citenexus-pdf-smoke .
#
# (run from the repository root; amd64 on an arm64 host runs under emulation)

FROM golang:1.26-bookworm AS go

FROM rust:1.95-slim-bookworm
ARG TARGETARCH
# pdfium-binaries chromium/8066 (2026-09-21), BSD-3; sha256 verified at pin time
ARG PDFIUM_TAG=chromium/8066
ARG PDFIUM_SHA256_amd64=0b43f405477cf2cfc4dbff06905093c3309756c6bca1fb9da99234a2ca97fed2
ARG PDFIUM_SHA256_arm64=0e6f90dccbc6b81fd5d7106abaf164c4222178f024c204d00d526b60fd2ad535

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates protobuf-compiler libprotobuf-dev gcc libc6-dev binutils \
 && rm -rf /var/lib/apt/lists/*
COPY --from=go /usr/local/go /usr/local/go
ENV PATH=/usr/local/go/bin:$PATH

RUN set -eux; \
    case "$TARGETARCH" in \
      amd64) asset=pdfium-linux-x64.tgz;   sum="$PDFIUM_SHA256_amd64" ;; \
      arm64) asset=pdfium-linux-arm64.tgz; sum="$PDFIUM_SHA256_arm64" ;; \
      *) echo "unsupported arch $TARGETARCH"; exit 1 ;; \
    esac; \
    curl -fsSL -o /tmp/pdfium.tgz "https://github.com/bblanchon/pdfium-binaries/releases/download/${PDFIUM_TAG}/${asset}"; \
    echo "${sum}  /tmp/pdfium.tgz" | sha256sum -c -; \
    mkdir -p /opt/pdfium && tar xzf /tmp/pdfium.tgz -C /opt/pdfium && rm /tmp/pdfium.tgz
ENV PDFIUM_DYNAMIC_LIB_PATH=/opt/pdfium/lib/libpdfium.so

# Emulated amd64 builds on an arm64 host run out of memory in the LTO link
# with full parallelism; cap it (override with --build-arg CARGO_BUILD_JOBS=N).
ARG CARGO_BUILD_JOBS=4
ENV CARGO_BUILD_JOBS=${CARGO_BUILD_JOBS}

WORKDIR /src
COPY rust rust
COPY golang golang
COPY conformance conformance
COPY docs/schema docs/schema

# The shipped .so: release profile (fat LTO).
RUN cd rust && cargo build --release --features pdf
# Tests: the `measure` profile (optimised, no LTO). Under emulation, linking
# each test binary with fat LTO in parallel was OOM-killed (SIGKILL).
RUN cd rust && CARGO_BUILD_JOBS=2 cargo test --profile measure --features pdf \
      --test pdf_units_test --test pdf_tables_test --test pdf_contract_test \
      --test pdf_contract_schema_test --test units_test --test numbers_test \
 && cd ../golang && CGO_ENABLED=1 go test -tags citenexus_ffi ./core/ -run 'TestPdf|TestOoxml|TestCitable' -v \
 && echo "--- runtime facts" \
 && ls -l /opt/pdfium/lib/libpdfium.so /src/rust/target/release/libcitenexus_core.so \
 && echo "libpdfium.so glibc floor: $(objdump -T /opt/pdfium/lib/libpdfium.so | grep -o 'GLIBC_[0-9.]*' | sort -uV | tail -1)" \
 && echo "libcitenexus_core.so glibc floor: $(objdump -T /src/rust/target/release/libcitenexus_core.so | grep -o 'GLIBC_[0-9.]*' | sort -uV | tail -1)" \
 && ldd --version | head -1
