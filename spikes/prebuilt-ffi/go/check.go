// Go loader — purego (pure Go, NO cgo, no toolchain, `go get`-clean).
// Loads the prebuilt core via dlopen at runtime.
package main

import (
	"fmt"
	"os"

	"github.com/ebitengine/purego"
)

func main() {
	libPath := os.Getenv("SPIKE_LIB")
	lib, err := purego.Dlopen(libPath, purego.RTLD_NOW|purego.RTLD_GLOBAL)
	if err != nil {
		fmt.Fprintln(os.Stderr, "[go] dlopen failed:", err)
		os.Exit(1)
	}

	var version func() string
	var add func(a, b int32) int32
	purego.RegisterLibFunc(&version, lib, "citenexus_spike_version")
	purego.RegisterLibFunc(&add, lib, "citenexus_spike_add")

	ver := version()
	total := add(2, 3)
	fmt.Printf("[go] version=%s add(2,3)=%d\n", ver, total)

	if ver != "citenexus-spike-0.1.0" || total != 5 {
		fmt.Fprintln(os.Stderr, "[go] MISMATCH")
		os.Exit(1)
	}
	fmt.Println("[go] OK")
}
