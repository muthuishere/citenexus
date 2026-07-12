> **Status:** implemented and green. Go `go test`/`vet`/`gofmt` clean; JS `tsc` +
> vitest (13 http/model tests) green; existing `model_wire` conformance unchanged.

## 1. Go parity (red → green)

- [x] 1.1 Failing test: `HTTPClient.ResolveHeaders` expands `${ENV}` at call time, `BuildHeaders` keeps the template, caller map unmutated; missing var → "" — `golang/models/http_test.go`
- [x] 1.2 Failing test: a model client with `WithHeaders` forwards the template to its transport; no options → only `Content-Type`
- [x] 1.3 Add `golang/models/http.go` (`ExpandEnv`, `HTTPClient` net/http, `WithHeaders` option, `wireHeaders`); wire `NewOpenAIChatGenerator`/`NewOpenAIEmbedding`/`NewAnthropicGenerator` (variadic opts); drop the old `jsonHeaders`

## 2. JS parity (red → green)

- [x] 2.1 Failing test: `HttpClient.resolveHeaders` expands `${ENV}` at call time, `buildHeaders` keeps the template, caller object unmutated; missing var → "" — `js/src/http.test.ts`
- [x] 2.2 Failing test: a model client forwards header templates; no headers → only `Content-Type`
- [x] 2.3 Add `js/src/http.ts` (`expandEnv`, `HttpClient`, `wireHeaders`); add `headers?` to `OpenAIChatConfig`/`OpenAIEmbedConfig`/`AnthropicConfig`; export from `index.ts`

## 3. Docs + gates

- [x] 3.1 `custom-endpoints.mdx` gains a Go + JS cross-port section; site builds
- [x] 3.2 Go `go test ./...` + `go vet` + `gofmt -l` clean; JS `tsc --noEmit` + vitest green; `model_wire` conformance unchanged
