package models

import (
	"bytes"
	"io"
	"net/http"
	"os"
	"regexp"
	"time"
)

// envRe matches ${ENV_VAR} in a header value. The value is resolved from the
// process environment at the REQUEST BOUNDARY (toolnexus style), so a secret's
// value never lives on a client, a config, or a log — only the ${NAME} template.
// Mirrors python citenexus.http._ENV_RE.
var envRe = regexp.MustCompile(`\$\{([A-Za-z0-9_]+)\}`)

const userAgent = "citenexus"

// defaultTimeout matches the Python HttpClient default.
const defaultTimeout = 60 * time.Second

// ExpandEnv replaces every ${ENV_VAR} in value with os.Getenv (a missing var ->
// ""). Called only when a request is sent; the resolved value is used once and
// never stored back. Mirrors python citenexus.http.expand_env.
func ExpandEnv(value string) string {
	return envRe.ReplaceAllStringFunc(value, func(match string) string {
		return os.Getenv(envRe.FindStringSubmatch(match)[1])
	})
}

// HTTPClient is the default Transport: a real net/http POST that expands ${ENV}
// in headers at call time. Mirrors python citenexus.http.HttpClient — the same
// merge order (User-Agent < client defaults < per-call) and the same rule that
// ${ENV} is materialized only in ResolveHeaders, for one request, never logged.
type HTTPClient struct {
	headers map[string]string
	client  *http.Client
}

// NewHTTPClient builds a default transport with optional client-level headers
// (themselves allowed to be ${ENV} templates) and a timeout (0 -> 60s).
func NewHTTPClient(headers map[string]string, timeout time.Duration) *HTTPClient {
	if timeout == 0 {
		timeout = defaultTimeout
	}
	return &HTTPClient{headers: headers, client: &http.Client{Timeout: timeout}}
}

// BuildHeaders merges User-Agent < client defaults < per-call (auth wins). Pure:
// the ${ENV} templates are preserved, not expanded.
func (c *HTTPClient) BuildHeaders(call map[string]string) map[string]string {
	out := map[string]string{"User-Agent": userAgent}
	for k, v := range c.headers {
		out[k] = v
	}
	for k, v := range call {
		out[k] = v
	}
	return out
}

// ResolveHeaders merges, then expands ${ENV} in every value — the ONLY place a
// header secret is materialized, for one request, never stored back.
func (c *HTTPClient) ResolveHeaders(call map[string]string) map[string]string {
	merged := c.BuildHeaders(call)
	out := make(map[string]string, len(merged))
	for k, v := range merged {
		out[k] = ExpandEnv(v)
	}
	return out
}

// Do implements Transport: POST body to url with resolved headers.
func (c *HTTPClient) Do(url string, body []byte, headers map[string]string) ([]byte, error) {
	req, err := http.NewRequest(http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	for k, v := range c.ResolveHeaders(headers) {
		req.Header.Set(k, v)
	}
	resp, err := c.client.Do(req)
	if err != nil {
		return nil, err
	}
	defer func() { _ = resp.Body.Close() }()
	return io.ReadAll(resp.Body)
}

// Transport adapts this client to the injected Transport seam.
func (c *HTTPClient) Transport() Transport { return c.Do }

// Option configures a model client. Variadic options keep the existing
// positional constructors backward-compatible while adding first-class headers.
type Option func(*clientOptions)

type clientOptions struct{ headers map[string]string }

// WithHeaders adds first-class auth/provider headers to a model client — pass
// ${ENV} templates like {"Authorization": "Bearer ${OPENAI_API_KEY}"}; the value
// is expanded by the transport at call time, never held on the client.
func WithHeaders(headers map[string]string) Option {
	return func(o *clientOptions) {
		o.headers = make(map[string]string, len(headers))
		for k, v := range headers {
			o.headers[k] = v
		}
	}
}

func applyOptions(opts []Option) map[string]string {
	o := &clientOptions{}
	for _, opt := range opts {
		opt(o)
	}
	return o.headers
}

// wireHeaders returns Content-Type plus any caller-supplied header templates.
// With no extra headers it is exactly {"Content-Type": "application/json"} — so
// the pinned model_wire conformance is unchanged.
func wireHeaders(extra map[string]string) map[string]string {
	out := map[string]string{"Content-Type": "application/json"}
	for k, v := range extra {
		out[k] = v
	}
	return out
}
