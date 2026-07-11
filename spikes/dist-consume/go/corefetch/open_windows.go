//go:build windows

package corefetch

import "syscall"

// Open loads the native DLL and returns a handle. Windows has no dlopen and
// purego v0.9 exposes no Dlopen/LoadLibrary there, so we use the stdlib
// syscall.LoadLibrary (no extra dependency). purego.RegisterLibFunc(&fn, handle,
// name) then works identically to the Unix path.
func Open(path string) (uintptr, error) {
	h, err := syscall.LoadLibrary(path)
	return uintptr(h), err
}
