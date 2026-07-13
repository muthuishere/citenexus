package config

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// writeFile is a tiny helper for the fixtures below.
func writeFile(t *testing.T, path, body string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
}

// Task 3.1 — resolution precedence env → project → global → defaults, plus
// nearest-ancestor project discovery from a subdirectory.
func TestResolutionPrecedence(t *testing.T) {
	root := t.TempDir()
	global := filepath.Join(root, "global", "config.yaml")
	writeFile(t, global, "mode: skill\npartition: from-global\nstorage:\n  path: /global/path\n")

	projectDir := filepath.Join(root, "proj")
	writeFile(t, filepath.Join(projectDir, ProjectFileName), "partition: from-project\n")

	// A deep subdirectory must still discover the project's citenexus.yaml.
	sub := filepath.Join(projectDir, "a", "b", "c")
	if err := os.MkdirAll(sub, 0o755); err != nil {
		t.Fatal(err)
	}

	env := map[string]string{"CITENEXUS_PARTITION": "from-env"}
	r := Resolver{StartDir: sub, GlobalPath: global, Getenv: func(k string) string { return env[k] }}

	cfg, src, err := r.Load()
	if err != nil {
		t.Fatal(err)
	}
	// env wins over project over global over defaults.
	if cfg.Partition != "from-env" {
		t.Errorf("partition: want from-env (env wins), got %q", cfg.Partition)
	}
	// global-only key survives (mode default is api; global set it to skill).
	if cfg.Mode != "skill" {
		t.Errorf("mode: want skill (from global), got %q", cfg.Mode)
	}
	// global overlaid a field the project did not set.
	if cfg.Storage.Path != "/global/path" {
		t.Errorf("storage.path: want /global/path, got %q", cfg.Storage.Path)
	}
	// default kept where nothing overrode it.
	if cfg.Storage.Backend != "local" {
		t.Errorf("storage.backend: want default local, got %q", cfg.Storage.Backend)
	}
	if src.ProjectFile != filepath.Join(projectDir, ProjectFileName) {
		t.Errorf("project source not reported: %q", src.ProjectFile)
	}
	if src.GlobalFile != global {
		t.Errorf("global source not reported: %q", src.GlobalFile)
	}
}

func TestDefaultsWhenNoFiles(t *testing.T) {
	r := Resolver{StartDir: t.TempDir(), GlobalPath: filepath.Join(t.TempDir(), "none.yaml"), Getenv: func(string) string { return "" }}
	cfg, src, err := r.Load()
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Mode != "api" || cfg.Storage.Backend != "local" || cfg.Partition != "default" {
		t.Errorf("defaults not applied: %+v", cfg)
	}
	if src.ProjectFile != "" || src.GlobalFile != "" {
		t.Errorf("expected no sources, got %+v", src)
	}
}

// Task 3.2 — ${ENV} header templates are stored verbatim (no literal secret) and
// resolved only at the request edge.
func TestSecretStaysTemplate(t *testing.T) {
	t.Setenv("MY_TEST_KEY", "super-secret-value")

	projectDir := t.TempDir()
	writeFile(t, filepath.Join(projectDir, ProjectFileName),
		"models:\n  llm:\n    base_url: https://api.openai.com/v1\n    model: gpt-4o-mini\n    headers:\n      Authorization: \"Bearer ${MY_TEST_KEY}\"\n")

	r := Resolver{StartDir: projectDir, GlobalPath: filepath.Join(t.TempDir(), "none.yaml"), Getenv: os.Getenv}
	cfg, _, err := r.Load()
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Models.LLM == nil {
		t.Fatal("llm model not loaded")
	}
	auth := cfg.Models.LLM.Headers["Authorization"]
	// The loaded config holds the TEMPLATE, never the resolved secret value.
	if auth != "Bearer ${MY_TEST_KEY}" {
		t.Errorf("header not stored verbatim: %q", auth)
	}
	if strings.Contains(auth, "super-secret-value") {
		t.Fatal("SECRET LEAKED into loaded config")
	}
}

func TestInitScaffoldNoLiteralSecret(t *testing.T) {
	dir := t.TempDir()
	path, err := InitProject(dir, false)
	if err != nil {
		t.Fatal(err)
	}
	body, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(body), "${OPENAI_API_KEY}") {
		t.Error("scaffold should use an ${ENV} template for auth")
	}
	// Re-init without --force must refuse.
	if _, err := InitProject(dir, false); err == nil {
		t.Error("re-init without force should error")
	}
	if _, err := InitProject(dir, true); err != nil {
		t.Errorf("re-init with force should succeed: %v", err)
	}
}

func TestGlobalGetSet(t *testing.T) {
	global := filepath.Join(t.TempDir(), "config.yaml")
	if err := SetGlobal(global, "mode", "skill"); err != nil {
		t.Fatal(err)
	}
	if err := SetGlobal(global, "models.llm.model", "gpt-4o-mini"); err != nil {
		t.Fatal(err)
	}
	v, ok, err := GetGlobal(global, "models.llm.model")
	if err != nil || !ok {
		t.Fatalf("get failed: ok=%v err=%v", ok, err)
	}
	if v != "gpt-4o-mini" {
		t.Errorf("got %q", v)
	}
	// A resolver reading this global file sees the values.
	cfg, _, err := Resolver{StartDir: t.TempDir(), GlobalPath: global, Getenv: func(string) string { return "" }}.Load()
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Mode != "skill" || cfg.Models.LLM == nil || cfg.Models.LLM.Model != "gpt-4o-mini" {
		t.Errorf("global get/set did not round-trip through Load: %+v", cfg)
	}
	if _, ok, _ := GetGlobal(global, "does.not.exist"); ok {
		t.Error("absent key should report ok=false")
	}
}
