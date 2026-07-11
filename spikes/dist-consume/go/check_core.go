// Go consume proof: fetch the prebuilt core from the pinned Release, SHA256-
// verify, purego-dlopen, call citenexus_core_version() — NO local build, no cgo.
package main

import (
	"fmt"
	"os"
	"regexp"

	"github.com/ebitengine/purego"

	"citenexus-dist-consume-go/corefetch"
)

func main() {
	path, err := corefetch.EnsureCore()
	if err != nil {
		fmt.Fprintln(os.Stderr, "[go] EnsureCore failed:", err)
		os.Exit(1)
	}
	fmt.Printf("[go] core at %s\n", path)

	// corefetch.Open is build-tagged: dlopen on Unix, LoadLibrary on Windows.
	handle, err := corefetch.Open(path)
	if err != nil {
		fmt.Fprintln(os.Stderr, "[go] load failed:", err)
		os.Exit(1)
	}
	var version func() string
	purego.RegisterLibFunc(&version, handle, "citenexus_core_version")

	ver := version()
	// NOTE: the release is TAGGED v0.7.0 but the cdylib embeds the Rust CRATE
	// version (rust/Cargo.toml), which was 0.6.0 at that tag. Integrity is proven
	// by the SHA256 gate in EnsureCore (it errors on mismatch); this call only
	// proves the symbol loads and returns a valid version string.
	fmt.Printf("[go] citenexus_core_version()=%q (release tag v%s)\n", ver, corefetch.CoreVersion)
	if !regexp.MustCompile(`^\d+\.\d+\.\d+`).MatchString(ver) {
		fmt.Fprintf(os.Stderr, "[go] FAIL: not a semver: %q\n", ver)
		os.Exit(1)
	}
	fmt.Println("[go] OK — fetched + SHA256-verified + purego-loaded prebuilt core, no toolchain/build")
}
