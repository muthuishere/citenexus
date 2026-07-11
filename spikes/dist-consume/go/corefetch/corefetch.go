// Package corefetch is the Go CONSUME side of the prebuilt-core model: on first
// use it downloads the matching citenexus-core native lib from the pinned GitHub
// Release, SHA256-verifies it against the published .sha256, caches it under
// ~/.cache/citenexus/<version>/, and hands back a path purego can dlopen.
//
// Why fetch (not go:embed): the real cdylib is ~150 MB (lancedb/arrow); embedding
// all four platforms would bloat every `go get`. Fetch pulls exactly one, once.
// The cgo `citenexus_ffi` build-tag path stays as the opt-in static alternative.
package corefetch

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"runtime"
	"strings"
)

// CoreVersion is the pinned citenexus-core release the prebuilt is fetched from.
// A Go release tag would bump this to match the Tier-1 native-libs artifacts.
const CoreVersion = "0.7.0"

const releaseBase = "https://github.com/muthuishere/citenexus/releases/download"

// assetName maps GOOS/GOARCH to the native-libs Release asset name.
func assetName() (string, error) {
	switch runtime.GOOS + "/" + runtime.GOARCH {
	case "darwin/arm64":
		return "citenexus_core-darwin-arm64.dylib", nil
	case "linux/amd64":
		return "citenexus_core-linux-amd64.so", nil
	case "linux/arm64":
		return "citenexus_core-linux-arm64.so", nil
	case "windows/amd64":
		return "citenexus_core-windows-amd64.dll", nil
	default:
		return "", fmt.Errorf("citenexus: no prebuilt core for %s/%s (build the cgo path with -tags citenexus_ffi)", runtime.GOOS, runtime.GOARCH)
	}
}

func cacheDir() (string, error) {
	if d := os.Getenv("CITENEXUS_CACHE_DIR"); d != "" {
		return d, nil
	}
	base, err := os.UserCacheDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(base, "citenexus", CoreVersion), nil
}

func sha256File(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer f.Close()
	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

func httpGet(url string) ([]byte, error) {
	// CITENEXUS_CORE_BASE_URL lets tests point at a local mirror / file server.
	if base := os.Getenv("CITENEXUS_CORE_BASE_URL"); base != "" {
		url = strings.Replace(url, releaseBase+"/v"+CoreVersion, strings.TrimRight(base, "/"), 1)
	}
	resp, err := http.Get(url) //nolint:gosec // pinned release URL
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("GET %s: %s", url, resp.Status)
	}
	return io.ReadAll(resp.Body)
}

// EnsureCore returns a local path to the verified native core, fetching and
// caching it on first use. Override the whole path with CITENEXUS_CORE_LIB.
func EnsureCore() (string, error) {
	if override := os.Getenv("CITENEXUS_CORE_LIB"); override != "" {
		return override, nil
	}
	asset, err := assetName()
	if err != nil {
		return "", err
	}
	dir, err := cacheDir()
	if err != nil {
		return "", err
	}
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", err
	}
	final := filepath.Join(dir, asset)

	// expected digest from the published .sha256 (first whitespace field)
	shaBytes, err := httpGet(fmt.Sprintf("%s/v%s/%s.sha256", releaseBase, CoreVersion, asset))
	if err != nil {
		return "", fmt.Errorf("fetch checksum: %w", err)
	}
	want := strings.Fields(string(shaBytes))
	if len(want) == 0 {
		return "", fmt.Errorf("empty checksum file for %s", asset)
	}
	wantHex := want[0]

	// cache hit — re-verify, discard a corrupt entry
	if got, err := sha256File(final); err == nil {
		if got == wantHex {
			return final, nil
		}
		_ = os.Remove(final)
	}

	// download, verify, publish atomically
	data, err := httpGet(fmt.Sprintf("%s/v%s/%s", releaseBase, CoreVersion, asset))
	if err != nil {
		return "", fmt.Errorf("fetch core: %w", err)
	}
	sum := sha256.Sum256(data)
	if got := hex.EncodeToString(sum[:]); got != wantHex {
		return "", fmt.Errorf("checksum mismatch for %s: got %s want %s", asset, got, wantHex)
	}
	tmp := final + ".part"
	if err := os.WriteFile(tmp, data, 0o644); err != nil { //nolint:gosec // loadable lib
		return "", err
	}
	if err := os.Rename(tmp, final); err != nil {
		return "", err
	}
	return final, nil
}
