//go:build !windows

package corefetch

import "github.com/ebitengine/purego"

// Open loads the native library and returns a handle. On Unix this is dlopen;
// purego.Dlopen and the RTLD_* constants are Unix-only (they don't compile on
// Windows), so the Windows handle path lives in open_windows.go.
func Open(path string) (uintptr, error) {
	return purego.Dlopen(path, purego.RTLD_NOW|purego.RTLD_GLOBAL)
}
