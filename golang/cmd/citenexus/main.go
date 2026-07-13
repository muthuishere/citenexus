// Command citenexus is the CiteNexus CLI: one installable binary exposing the
// evidence-first RAG core from a shell (and drivable headless by an agent skill).
// It ingests artifacts, retrieves cite-only candidates, and answers with the
// cite-or-abstain guarantee — models injected via ${ENV}-auth config, never a
// literal secret. The default build is pure Go (text extraction); the
// citenexus_ffi build static-links the Rust core for full-format extraction.
package main

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"github.com/muthuishere/citenexus/golang/cli/config"
	"github.com/muthuishere/citenexus/golang/cli/engine"
	"github.com/muthuishere/citenexus/golang/cli/skills"
	"github.com/muthuishere/citenexus/golang/cli/store"
	"github.com/muthuishere/citenexus/golang/result"
)

// version is the CLI version; the npm package and GH release tag track it 1:1.
const version = "0.9.0"

const usage = `citenexus — evidence-first RAG CLI

Usage: citenexus [--config <path>] [--json] [--partition <name>] <command> [args]

Commands:
  init [dir]                 scaffold a commit-safe citenexus.yaml
  config get <key>           read a global config key
  config set <key> <value>   write a global config key
  ingest <path>              extract → chunk → embed → store an artifact
  retrieve "<query>"         fused, cite-only candidates (no model)
  ask "<question>"           grounded answer or refusal (needs an llm model)
  install --skills           install the agent skill into ~/.claude and ~/.agents
  version                    print the version

Global flags:
  --config <path>     use an explicit config file (skips discovery)
  --json              machine-readable output
  --partition <name>  operate on a named partition (default: default)

Config resolves environment → ./citenexus.yaml → ~/.config/citenexus/config.yaml
→ defaults. Secrets are ${ENV} header templates only — a config is safe to commit.
`

// globals holds the parsed global flags.
type globals struct {
	configPath string
	jsonOut    bool
	partition  string
}

func main() {
	if err := run(os.Args[1:], os.Stdout, os.Stderr); err != nil {
		fmt.Fprintln(os.Stderr, "citenexus: "+err.Error())
		os.Exit(1)
	}
}

// run is the testable entry point: it parses args and dispatches, writing to out.
func run(args []string, out, errOut io.Writer) error {
	g, rest, err := parseGlobals(args)
	if err != nil {
		return err
	}
	if len(rest) == 0 {
		fmt.Fprint(out, usage)
		return nil
	}

	cmd, cmdArgs := rest[0], rest[1:]
	switch cmd {
	case "version", "--version", "-v":
		fmt.Fprintln(out, "citenexus "+version)
		return nil
	case "help", "--help", "-h":
		fmt.Fprint(out, usage)
		return nil
	case "init":
		return cmdInit(cmdArgs, out)
	case "config":
		return cmdConfig(g, cmdArgs, out)
	case "install":
		return cmdInstall(cmdArgs, out)
	case "ingest":
		return cmdIngest(g, cmdArgs, out)
	case "retrieve":
		return cmdRetrieve(g, cmdArgs, out)
	case "ask":
		return cmdAsk(g, cmdArgs, out)
	default:
		return fmt.Errorf("unknown command %q (try: citenexus help)", cmd)
	}
}

// parseGlobals extracts the leading global flags, returning the remaining args.
func parseGlobals(args []string) (globals, []string, error) {
	g := globals{}
	var rest []string
	i := 0
	for i < len(args) {
		a := args[i]
		switch {
		case a == "--config":
			if i+1 >= len(args) {
				return g, nil, fmt.Errorf("--config needs a path")
			}
			g.configPath = args[i+1]
			i += 2
		case strings.HasPrefix(a, "--config="):
			g.configPath = strings.TrimPrefix(a, "--config=")
			i++
		case a == "--json":
			g.jsonOut = true
			i++
		case a == "--partition":
			if i+1 >= len(args) {
				return g, nil, fmt.Errorf("--partition needs a name")
			}
			g.partition = args[i+1]
			i += 2
		case strings.HasPrefix(a, "--partition="):
			g.partition = strings.TrimPrefix(a, "--partition=")
			i++
		default:
			// First non-global token: the command and everything after it.
			rest = append(rest, args[i:]...)
			return g, rest, nil
		}
	}
	return g, rest, nil
}

// loadConfig resolves the effective config, honoring --config and --partition.
func (g globals) loadConfig() (config.Config, error) {
	r := config.DefaultResolver()
	if g.configPath != "" {
		r.ExplicitFile = g.configPath
	}
	cfg, _, err := r.Load()
	if err != nil {
		return cfg, err
	}
	if g.partition != "" {
		cfg.Partition = g.partition
	}
	return cfg, nil
}

// buildEngine wires the store + injected extractor + models from config.
func (g globals) buildEngine() (*engine.Engine, config.Config, error) {
	cfg, err := g.loadConfig()
	if err != nil {
		return nil, cfg, err
	}
	if cfg.Storage.Backend != "local" {
		return nil, cfg, fmt.Errorf("storage backend %q not supported by the CLI yet (use: local)", cfg.Storage.Backend)
	}
	st, err := store.Open(cfg.Storage.Path)
	if err != nil {
		return nil, cfg, err
	}
	emb, err := engine.NewEmbedder(cfg.Models.Embedding)
	if err != nil {
		return nil, cfg, err
	}
	gen, err := engine.NewGenerator(cfg.Models.LLM)
	if err != nil {
		return nil, cfg, err
	}
	e := &engine.Engine{
		Store:     st,
		Extractor: newExtractor(), // build-tag provided: pure text | Rust core
		Embedder:  emb,
		Generator: gen,
		Partition: cfg.Partition,
	}
	return e, cfg, nil
}

func cmdInit(args []string, out io.Writer) error {
	dir := "."
	force := false
	for _, a := range args {
		if a == "--force" {
			force = true
			continue
		}
		dir = a
	}
	path, err := config.InitProject(dir, force)
	if err != nil {
		return err
	}
	fmt.Fprintln(out, "wrote "+path)
	return nil
}

func cmdConfig(g globals, args []string, out io.Writer) error {
	globalPath := config.GlobalConfigPath(os.Getenv)
	if len(args) == 0 {
		return fmt.Errorf("config needs: get <key> | set <key> <value>")
	}
	switch args[0] {
	case "get":
		if len(args) < 2 {
			return fmt.Errorf("config get needs a key")
		}
		v, ok, err := config.GetGlobal(globalPath, args[1])
		if err != nil {
			return err
		}
		if !ok {
			return fmt.Errorf("config: key %q not set", args[1])
		}
		fmt.Fprintln(out, v)
		return nil
	case "set":
		if len(args) < 3 {
			return fmt.Errorf("config set needs <key> <value>")
		}
		if err := config.SetGlobal(globalPath, args[1], args[2]); err != nil {
			return err
		}
		fmt.Fprintln(out, "set "+args[1])
		return nil
	default:
		return fmt.Errorf("config: unknown subcommand %q", args[0])
	}
}

func cmdInstall(args []string, out io.Writer) error {
	wantSkills := false
	for _, a := range args {
		if a == "--skills" {
			wantSkills = true
		}
	}
	if !wantSkills {
		return fmt.Errorf("install: only --skills is supported")
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return err
	}
	dirs, err := skills.InstallToHome(home)
	if err != nil {
		return err
	}
	for _, d := range dirs {
		fmt.Fprintln(out, "installed skill → "+d)
	}
	return nil
}

func cmdIngest(g globals, args []string, out io.Writer) error {
	if len(args) == 0 {
		return fmt.Errorf("ingest needs a <path>")
	}
	e, _, err := g.buildEngine()
	if err != nil {
		return err
	}
	path := args[0]
	data, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	docID := documentID(path)
	n, err := e.Ingest(data, sourceTypeFor(path), docID)
	if err != nil {
		return err
	}
	if g.jsonOut {
		return writeJSON(out, map[string]any{"document_id": docID, "units": n})
	}
	fmt.Fprintf(out, "ingested %s → %d evidence units\n", docID, n)
	return nil
}

func cmdRetrieve(g globals, args []string, out io.Writer) error {
	if len(args) == 0 {
		return fmt.Errorf("retrieve needs a \"<query>\"")
	}
	e, _, err := g.buildEngine()
	if err != nil {
		return err
	}
	cands, err := e.Retrieve(args[0])
	if err != nil {
		return err
	}
	if g.jsonOut {
		if cands == nil {
			cands = []engine.Candidate{}
		}
		return writeJSON(out, cands)
	}
	if len(cands) == 0 {
		fmt.Fprintln(out, "no candidates")
		return nil
	}
	for i, c := range cands {
		fmt.Fprintf(out, "%d. [%s] %s\n", i+1, c.DocumentID, oneLine(c.Text))
	}
	return nil
}

func cmdAsk(g globals, args []string, out io.Writer) error {
	if len(args) == 0 {
		return fmt.Errorf("ask needs a \"<question>\"")
	}
	e, _, err := g.buildEngine()
	if err != nil {
		return err
	}
	res, err := e.Ask(args[0], "")
	if err != nil {
		return err
	}
	if g.jsonOut {
		return writeJSON(out, res)
	}
	printResult(out, res)
	return nil
}

func printResult(out io.Writer, res result.Result) {
	if res.Evidence.Decision == result.DecisionRefused {
		fmt.Fprintln(out, res.Answer)
		return
	}
	fmt.Fprintln(out, res.Answer)
	for _, s := range res.Sources {
		fmt.Fprintf(out, "  ↳ %s: %s\n", s.Document, oneLine(s.Passage))
	}
}

func writeJSON(out io.Writer, v any) error {
	enc := json.NewEncoder(out)
	enc.SetIndent("", "  ")
	return enc.Encode(v)
}

// documentID derives a stable id from a path: its base name without extension.
func documentID(path string) string {
	base := filepath.Base(path)
	if ext := filepath.Ext(base); ext != "" {
		base = strings.TrimSuffix(base, ext)
	}
	return base
}

// sourceTypeFor maps a file extension to the extractor source type.
func sourceTypeFor(path string) string {
	ext := strings.ToLower(strings.TrimPrefix(filepath.Ext(path), "."))
	switch ext {
	case "":
		return "plain"
	case "text":
		return "txt"
	case "markdown":
		return "md"
	default:
		return ext
	}
}

func oneLine(s string) string {
	s = strings.ReplaceAll(s, "\n", " ")
	if len(s) > 120 {
		return s[:117] + "..."
	}
	return s
}
