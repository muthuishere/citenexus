package main

import (
	"bytes"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// Task 2.1 — version and help list the command set.
func TestVersionAndHelp(t *testing.T) {
	var out bytes.Buffer
	if err := run([]string{"version"}, &out, &out); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out.String(), version) {
		t.Errorf("version output missing %q: %q", version, out.String())
	}

	out.Reset()
	if err := run([]string{"help"}, &out, &out); err != nil {
		t.Fatal(err)
	}
	help := out.String()
	for _, cmd := range []string{"init", "config", "ingest", "ask", "retrieve", "install --skills"} {
		if !strings.Contains(help, cmd) {
			t.Errorf("help missing command %q", cmd)
		}
	}
	for _, flag := range []string{"--config", "--json", "--partition"} {
		if !strings.Contains(help, flag) {
			t.Errorf("help missing global flag %q", flag)
		}
	}
}

func TestUnknownCommand(t *testing.T) {
	var out bytes.Buffer
	if err := run([]string{"frobnicate"}, &out, &out); err == nil {
		t.Fatal("expected error for unknown command")
	}
}

func TestNoArgsPrintsUsage(t *testing.T) {
	var out bytes.Buffer
	if err := run(nil, &out, &out); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out.String(), "Usage:") {
		t.Errorf("no-args should print usage, got %q", out.String())
	}
}

// Task 4.1 — hermetic init → ingest → retrieve → ask over fakes, through the
// built binary (default pure build, no network, no Rust core).
func TestIntegrationThroughBuiltBinary(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping binary build in -short mode")
	}
	bin := filepath.Join(t.TempDir(), "citenexus")
	build := exec.Command("go", "build", "-o", bin, ".")
	build.Stderr = os.Stderr
	if err := build.Run(); err != nil {
		t.Fatalf("build failed: %v", err)
	}

	proj := t.TempDir()
	home := t.TempDir()
	// A committable config with FAKE models: hermetic, offline, deterministic.
	cfg := `storage: { backend: local, path: ./.citenexus }
signals: [embedding, text]
mode: api
models:
  embedding: { provider: fake }
  llm: { provider: fake }
`
	if err := os.WriteFile(filepath.Join(proj, "citenexus.yaml"), []byte(cfg), 0o644); err != nil {
		t.Fatal(err)
	}
	corpus := "The termination notice period is thirty days for salaried employees.\n\nAnnual leave accrues at two point five days per month."
	if err := os.WriteFile(filepath.Join(proj, "policy.txt"), []byte(corpus), 0o644); err != nil {
		t.Fatal(err)
	}

	runBin := func(args ...string) (string, error) {
		cmd := exec.Command(bin, args...)
		cmd.Dir = proj
		cmd.Env = append(os.Environ(), "HOME="+home)
		var out, errBuf bytes.Buffer
		cmd.Stdout, cmd.Stderr = &out, &errBuf
		err := cmd.Run()
		if err != nil {
			return out.String() + errBuf.String(), err
		}
		return out.String(), nil
	}

	if o, err := runBin("ingest", "policy.txt"); err != nil {
		t.Fatalf("ingest: %v\n%s", err, o)
	}

	// retrieve --json surfaces the ingested document.
	o, err := runBin("--json", "retrieve", "termination notice period")
	if err != nil {
		t.Fatalf("retrieve: %v\n%s", err, o)
	}
	var cands []map[string]any
	if err := json.Unmarshal([]byte(o), &cands); err != nil {
		t.Fatalf("retrieve json: %v\n%s", err, o)
	}
	if len(cands) == 0 || cands[0]["document_id"] != "policy" {
		t.Fatalf("retrieve did not surface policy: %s", o)
	}

	// ask --json returns a grounded, answered Result.
	o, err = runBin("--json", "ask", "What is the termination notice period?")
	if err != nil {
		t.Fatalf("ask: %v\n%s", err, o)
	}
	var res map[string]any
	if err := json.Unmarshal([]byte(o), &res); err != nil {
		t.Fatalf("ask json: %v\n%s", err, o)
	}
	ev, _ := res["evidence"].(map[string]any)
	if ev == nil || ev["decision"] != "answered" {
		t.Fatalf("ask not answered: %s", o)
	}

	// ask off-topic → refusal (no content-token overlap with the corpus).
	o, err = runBin("--json", "ask", "Who painted the Mona Lisa?")
	if err != nil {
		t.Fatalf("ask refusal: %v\n%s", err, o)
	}
	_ = json.Unmarshal([]byte(o), &res)
	ev, _ = res["evidence"].(map[string]any)
	if ev == nil || ev["decision"] != "refused" {
		t.Fatalf("off-topic ask should refuse: %s", o)
	}
}

// install --skills writes both skill dirs under a temp HOME.
func TestInstallSkillsThroughRun(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	var out bytes.Buffer
	if err := run([]string{"install", "--skills"}, &out, &out); err != nil {
		t.Fatal(err)
	}
	for _, p := range []string{
		filepath.Join(home, ".claude", "skills", "citenexus", "SKILL.md"),
		filepath.Join(home, ".agents", "skills", "citenexus", "SKILL.md"),
	} {
		if _, err := os.Stat(p); err != nil {
			t.Errorf("expected %s: %v", p, err)
		}
	}
}
