// Package config is the dual-level CiteNexus CLI configuration: built-in
// defaults ← global (~/.config/citenexus/config.yaml) ← project
// (./citenexus.yaml, discovered by walking up from the working directory) ←
// environment, highest wins. Secrets are NEVER stored: model auth lives only as
// ${ENV_VAR} header templates that the model HTTP client expands at the request
// boundary (golang/models.ExpandEnv). A citenexus.yaml is therefore always safe
// to commit.
package config

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"gopkg.in/yaml.v3"
)

// ProjectFileName is the per-folder config discovered by walking up from CWD.
const ProjectFileName = "citenexus.yaml"

// ModelConfig is one injected OpenAI-compatible endpoint. Provider "fake" selects
// the deterministic offline double (hermetic tests); "" / "openai" is the real
// HTTP client. Headers hold ${ENV} templates only — never a literal key.
type ModelConfig struct {
	Provider string            `yaml:"provider,omitempty"`
	BaseURL  string            `yaml:"base_url,omitempty"`
	Model    string            `yaml:"model,omitempty"`
	Headers  map[string]string `yaml:"headers,omitempty"`
}

// Models groups the embedding and llm endpoints.
type Models struct {
	Embedding *ModelConfig `yaml:"embedding,omitempty"`
	LLM       *ModelConfig `yaml:"llm,omitempty"`
}

// Storage selects the evidence backend. Only "local" (a directory of JSONL EU
// rows) ships in this slice; "s3" is reserved.
type Storage struct {
	Backend string `yaml:"backend,omitempty"`
	Path    string `yaml:"path,omitempty"`
}

// Config is the fully-resolved CLI configuration.
type Config struct {
	Storage   Storage  `yaml:"storage,omitempty"`
	Signals   []string `yaml:"signals,omitempty"`
	Mode      string   `yaml:"mode,omitempty"`
	Partition string   `yaml:"partition,omitempty"`
	Models    Models   `yaml:"models,omitempty"`
}

// Defaults is the built-in base layer (lowest precedence).
func Defaults() Config {
	return Config{
		Storage:   Storage{Backend: "local", Path: "./.citenexus"},
		Signals:   []string{"embedding", "text"},
		Mode:      "api",
		Partition: "default",
	}
}

// Sources records where the resolved config came from, for --json / debugging.
type Sources struct {
	ProjectFile string // absolute path of the discovered citenexus.yaml, or ""
	GlobalFile  string // absolute path of the global config, or ""
}

// Resolver holds the injectable inputs so resolution is hermetic in tests.
type Resolver struct {
	StartDir     string              // directory to begin the upward project search
	GlobalPath   string              // path to the global config file
	ExplicitFile string              // --config: use this file as the project layer, skip discovery
	Getenv       func(string) string // environment lookup (os.Getenv in production)
}

// DefaultResolver wires a Resolver to the real process environment: CWD for the
// project search, $XDG_CONFIG_HOME/citenexus or ~/.config/citenexus for global.
func DefaultResolver() Resolver {
	cwd, _ := os.Getwd()
	return Resolver{StartDir: cwd, GlobalPath: GlobalConfigPath(os.Getenv), Getenv: os.Getenv}
}

// GlobalConfigPath is $XDG_CONFIG_HOME/citenexus/config.yaml, else
// $HOME/.config/citenexus/config.yaml.
func GlobalConfigPath(getenv func(string) string) string {
	base := getenv("XDG_CONFIG_HOME")
	if base == "" {
		base = filepath.Join(getenv("HOME"), ".config")
	}
	return filepath.Join(base, "citenexus", "config.yaml")
}

// FindProjectFile walks up from startDir returning the nearest citenexus.yaml, or
// "" if none exists up to the filesystem root (git-style discovery).
func FindProjectFile(startDir string) string {
	dir := startDir
	for {
		candidate := filepath.Join(dir, ProjectFileName)
		if fi, err := os.Stat(candidate); err == nil && !fi.IsDir() {
			return candidate
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			return ""
		}
		dir = parent
	}
}

// Load resolves the effective config with precedence defaults < global < project
// < environment, and reports which files contributed.
func (r Resolver) Load() (Config, Sources, error) {
	getenv := r.Getenv
	if getenv == nil {
		getenv = os.Getenv
	}
	cfg := Defaults()
	var src Sources

	if r.GlobalPath != "" {
		if global, ok, err := readFile(r.GlobalPath); err != nil {
			return cfg, src, err
		} else if ok {
			merge(&cfg, global)
			src.GlobalFile = r.GlobalPath
		}
	}

	// --config forces an explicit project layer and skips upward discovery.
	if r.ExplicitFile != "" {
		project, ok, err := readFile(r.ExplicitFile)
		if err != nil {
			return cfg, src, err
		}
		if !ok {
			return cfg, src, fmt.Errorf("config: --config file not found: %s", r.ExplicitFile)
		}
		merge(&cfg, project)
		src.ProjectFile = r.ExplicitFile
	} else if r.StartDir != "" {
		if projectPath := FindProjectFile(r.StartDir); projectPath != "" {
			project, _, err := readFile(projectPath)
			if err != nil {
				return cfg, src, err
			}
			merge(&cfg, project)
			src.ProjectFile = projectPath
		}
	}

	applyEnv(&cfg, getenv)
	return cfg, src, nil
}

// readFile parses a config file; ok=false (no error) when the file is absent.
func readFile(path string) (Config, bool, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return Config{}, false, nil
		}
		return Config{}, false, fmt.Errorf("config: read %s: %w", path, err)
	}
	var c Config
	if err := yaml.Unmarshal(data, &c); err != nil {
		return Config{}, false, fmt.Errorf("config: parse %s: %w", path, err)
	}
	return c, true, nil
}

// merge overlays the set (non-empty) fields of over onto base.
func merge(base *Config, over Config) {
	if over.Storage.Backend != "" {
		base.Storage.Backend = over.Storage.Backend
	}
	if over.Storage.Path != "" {
		base.Storage.Path = over.Storage.Path
	}
	if len(over.Signals) > 0 {
		base.Signals = over.Signals
	}
	if over.Mode != "" {
		base.Mode = over.Mode
	}
	if over.Partition != "" {
		base.Partition = over.Partition
	}
	if over.Models.Embedding != nil {
		base.Models.Embedding = over.Models.Embedding
	}
	if over.Models.LLM != nil {
		base.Models.LLM = over.Models.LLM
	}
}

// applyEnv overlays CITENEXUS_* environment variables (highest precedence).
func applyEnv(cfg *Config, getenv func(string) string) {
	if v := getenv("CITENEXUS_STORAGE_BACKEND"); v != "" {
		cfg.Storage.Backend = v
	}
	if v := getenv("CITENEXUS_STORAGE_PATH"); v != "" {
		cfg.Storage.Path = v
	}
	if v := getenv("CITENEXUS_MODE"); v != "" {
		cfg.Mode = v
	}
	if v := getenv("CITENEXUS_PARTITION"); v != "" {
		cfg.Partition = v
	}
	if v := getenv("CITENEXUS_SIGNALS"); v != "" {
		parts := strings.Split(v, ",")
		out := make([]string, 0, len(parts))
		for _, p := range parts {
			if p = strings.TrimSpace(p); p != "" {
				out = append(out, p)
			}
		}
		if len(out) > 0 {
			cfg.Signals = out
		}
	}
}
