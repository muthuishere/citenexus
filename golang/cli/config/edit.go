package config

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"gopkg.in/yaml.v3"
)

// starterProject is the citenexus.yaml `init` scaffolds: a committable,
// secret-free starting point. Auth is a ${ENV} template, never a literal key.
const starterProject = `# CiteNexus project config — safe to commit (holds no secrets).
storage:
  backend: local
  path: ./.citenexus
signals: [embedding, text]
mode: api                       # api | skill
models:
  embedding:
    provider: openai            # or: fake (deterministic, offline)
    base_url: https://api.openai.com/v1
    model: text-embedding-3-small
    headers:
      Authorization: "Bearer ${OPENAI_API_KEY}"
  llm:
    provider: openai
    base_url: https://api.openai.com/v1
    model: gpt-4o-mini
    headers:
      Authorization: "Bearer ${OPENAI_API_KEY}"
`

// InitProject writes a starter citenexus.yaml into dir. It refuses to overwrite
// an existing file unless force is set. Returns the path written.
func InitProject(dir string, force bool) (string, error) {
	path := filepath.Join(dir, ProjectFileName)
	if !force {
		if _, err := os.Stat(path); err == nil {
			return path, fmt.Errorf("config: %s already exists (use --force to overwrite)", path)
		}
	}
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return path, err
	}
	if err := os.WriteFile(path, []byte(starterProject), 0o644); err != nil {
		return path, err
	}
	return path, nil
}

// GetGlobal reads a dotted key (e.g. "mode", "models.llm.model") from the global
// config file. ok=false when the key is absent.
func GetGlobal(globalPath, key string) (value string, ok bool, err error) {
	m, err := loadMap(globalPath)
	if err != nil {
		return "", false, err
	}
	node, ok := lookup(m, strings.Split(key, "."))
	if !ok {
		return "", false, nil
	}
	return fmt.Sprintf("%v", node), true, nil
}

// SetGlobal writes value at a dotted key in the global config file, creating the
// file and any intermediate maps. Unknown/extra fields are preserved verbatim.
func SetGlobal(globalPath, key, value string) error {
	m, err := loadMap(globalPath)
	if err != nil {
		return err
	}
	if m == nil {
		m = map[string]any{}
	}
	assign(m, strings.Split(key, "."), value)
	if err := os.MkdirAll(filepath.Dir(globalPath), 0o755); err != nil {
		return err
	}
	out, err := yaml.Marshal(m)
	if err != nil {
		return err
	}
	return os.WriteFile(globalPath, out, 0o644)
}

// loadMap reads the global config as a generic map (nil when the file is absent),
// preserving any keys the typed Config does not model.
func loadMap(path string) (map[string]any, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}
	m := map[string]any{}
	if err := yaml.Unmarshal(data, &m); err != nil {
		return nil, fmt.Errorf("config: parse %s: %w", path, err)
	}
	return m, nil
}

func lookup(m map[string]any, path []string) (any, bool) {
	var cur any = m
	for _, seg := range path {
		asMap, ok := cur.(map[string]any)
		if !ok {
			return nil, false
		}
		cur, ok = asMap[seg]
		if !ok {
			return nil, false
		}
	}
	return cur, true
}

func assign(m map[string]any, path []string, value string) {
	cur := m
	for _, seg := range path[:len(path)-1] {
		next, ok := cur[seg].(map[string]any)
		if !ok {
			next = map[string]any{}
			cur[seg] = next
		}
		cur = next
	}
	cur[path[len(path)-1]] = value
}
