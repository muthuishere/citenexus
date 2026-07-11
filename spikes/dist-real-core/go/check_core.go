// Go loader — purego (pure Go, NO cgo, no toolchain). Loads the REAL core via
// dlopen/LoadLibrary at runtime and calls `citenexus_core_version()`.
package main

import (
	"fmt"
	"os"
	"regexp"
	"strings"

	"github.com/ebitengine/purego"
)

func main() {
	libPath := os.Getenv("CORE_LIB")
	lib, err := purego.Dlopen(libPath, purego.RTLD_NOW|purego.RTLD_GLOBAL)
	if err != nil {
		fmt.Fprintln(os.Stderr, "[go] dlopen failed:", err)
		os.Exit(1)
	}

	var version func() string
	purego.RegisterLibFunc(&version, lib, "citenexus_core_version")

	ver := version()
	fmt.Printf("[go] citenexus_core_version()=%q\n", ver)

	expected := strings.TrimSpace(os.Getenv("EXPECT_CORE_VERSION"))
	if !regexp.MustCompile(`^\d+\.\d+\.\d+`).MatchString(ver) {
		fmt.Fprintf(os.Stderr, "[go] MISMATCH: not a semver: %q\n", ver)
		os.Exit(1)
	}
	if expected != "" && ver != expected {
		fmt.Fprintf(os.Stderr, "[go] MISMATCH: got %q, expected %q\n", ver, expected)
		os.Exit(1)
	}
	fmt.Println("[go] OK")
}
