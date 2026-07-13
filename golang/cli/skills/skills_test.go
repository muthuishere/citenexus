package skills

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// Task 5.1 — install --skills writes the skill into BOTH locations, idempotently.
func TestInstallToHomeBothLocationsIdempotent(t *testing.T) {
	home := t.TempDir()

	dirs, err := InstallToHome(home)
	if err != nil {
		t.Fatal(err)
	}
	want := []string{
		filepath.Join(home, ".claude", "skills", "citenexus"),
		filepath.Join(home, ".agents", "skills", "citenexus"),
	}
	if len(dirs) != 2 || dirs[0] != want[0] || dirs[1] != want[1] {
		t.Fatalf("unexpected target dirs: %v", dirs)
	}

	for _, dir := range want {
		skill := filepath.Join(dir, "SKILL.md")
		body, err := os.ReadFile(skill)
		if err != nil {
			t.Fatalf("SKILL.md missing at %s: %v", skill, err)
		}
		if !strings.Contains(string(body), "name: citenexus") {
			t.Errorf("SKILL.md at %s missing frontmatter", dir)
		}
		if _, err := os.Stat(filepath.Join(dir, "references", "commands.md")); err != nil {
			t.Errorf("references/commands.md missing at %s: %v", dir, err)
		}
	}

	// Idempotent: a second run must not error and must leave content unchanged.
	before, _ := os.ReadFile(filepath.Join(want[0], "SKILL.md"))
	if _, err := InstallToHome(home); err != nil {
		t.Fatalf("re-install errored: %v", err)
	}
	after, _ := os.ReadFile(filepath.Join(want[0], "SKILL.md"))
	if string(before) != string(after) {
		t.Error("re-install changed SKILL.md content")
	}
}
