// Package skills embeds the bundled CiteNexus agent skill and installs it into
// the agent skill directories, the windowctl/playwright-cli pattern: one
// `citenexus install --skills` writes SKILL.md (+ references/) into both
// ~/.claude/skills/citenexus/ and ~/.agents/skills/citenexus/, idempotently.
package skills

import (
	"embed"
	"io/fs"
	"os"
	"path/filepath"
)

//go:embed assets
var assets embed.FS

// SkillName is the installed skill's directory name.
const SkillName = "citenexus"

// TargetDirs returns the two skill install roots for a given home directory:
// <home>/.claude/skills/citenexus and <home>/.agents/skills/citenexus.
func TargetDirs(home string) []string {
	return []string{
		filepath.Join(home, ".claude", "skills", SkillName),
		filepath.Join(home, ".agents", "skills", SkillName),
	}
}

// InstallToHome writes the bundled skill into both TargetDirs(home). Idempotent:
// re-running overwrites files in place and never errors. Returns the dirs written.
func InstallToHome(home string) ([]string, error) {
	dirs := TargetDirs(home)
	for _, dir := range dirs {
		if err := InstallTo(dir); err != nil {
			return nil, err
		}
	}
	return dirs, nil
}

// InstallTo materializes the embedded assets/ tree into dir (dir becomes the
// skill root, i.e. assets/SKILL.md → dir/SKILL.md).
func InstallTo(dir string) error {
	return fs.WalkDir(assets, "assets", func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		rel, err := filepath.Rel("assets", path)
		if err != nil {
			return err
		}
		dest := filepath.Join(dir, rel)
		if d.IsDir() {
			return os.MkdirAll(dest, 0o755)
		}
		data, err := assets.ReadFile(path)
		if err != nil {
			return err
		}
		if err := os.MkdirAll(filepath.Dir(dest), 0o755); err != nil {
			return err
		}
		return os.WriteFile(dest, data, 0o644)
	})
}
