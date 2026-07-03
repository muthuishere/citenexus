package models

import (
	"encoding/json"
	"reflect"
	"testing"

	"github.com/muthuishere/citenexus-go/internal/conform"
)

// The §5 HTTP model clients are proven against the shared model_wire.json
// fixture — request bodies and parsed responses must match the Python reference
// exactly, over ALL cases, no leniency. Follows the tokenize exemplar.

type wireFixture struct {
	Requests []struct {
		Name   string          `json:"name"`
		Client string          `json:"client"`
		Config wireConfig      `json:"config"`
		Inputs wireInputs      `json:"inputs"`
		Expect json.RawMessage `json:"expected_request"`
	} `json:"requests"`
	Responses []struct {
		Name         string          `json:"name"`
		Client       string          `json:"client"`
		ResponseBody json.RawMessage `json:"response_body"`
		Expected     json.RawMessage `json:"expected"`
	} `json:"responses"`
}

type wireConfig struct {
	BaseURL   string `json:"base_url"`
	Model     string `json:"model"`
	MaxTokens *int   `json:"max_tokens"`
}

type wireInputs struct {
	Question       string   `json:"question"`
	Passage        string   `json:"passage"`
	AnswerLanguage string   `json:"answer_language"`
	Texts          []string `json:"texts"`
}

type capture struct {
	url     string
	body    []byte
	headers map[string]string
}

// capturing records the request and returns a canned response.
func capturing(cap *capture, response string) Transport {
	return func(url string, body []byte, headers map[string]string) ([]byte, error) {
		cap.url = url
		cap.body = body
		cap.headers = headers
		return []byte(response), nil
	}
}

// canned returns a fixed response body, ignoring the request.
func canned(response []byte) Transport {
	return func(url string, body []byte, headers map[string]string) ([]byte, error) {
		return response, nil
	}
}

func TestModelWireRequests(t *testing.T) {
	var fx wireFixture
	conform.Case(t, "model_wire.json", &fx)
	if len(fx.Requests) == 0 {
		t.Fatal("no request cases loaded")
	}

	for _, c := range fx.Requests {
		t.Run(c.Name, func(t *testing.T) {
			cap := &capture{}
			transport := capturing(cap, "{}")

			switch c.Client {
			case "openai_chat":
				g := NewOpenAIChatGenerator(c.Config.BaseURL, c.Config.Model, 0.0, c.Config.MaxTokens, transport)
				if _, err := g.Answer(c.Inputs.Question, c.Inputs.Passage, c.Inputs.AnswerLanguage); err != nil {
					t.Fatalf("Answer: %v", err)
				}
			case "anthropic":
				maxTokens := DefaultAnthropicMaxTokens
				if c.Config.MaxTokens != nil {
					maxTokens = *c.Config.MaxTokens
				}
				g := NewAnthropicGenerator(c.Config.BaseURL, c.Config.Model, 0.0, maxTokens, transport)
				if _, err := g.Answer(c.Inputs.Question, c.Inputs.Passage, c.Inputs.AnswerLanguage); err != nil {
					t.Fatalf("Answer: %v", err)
				}
			case "openai_embed":
				e := NewOpenAIEmbedding(c.Config.BaseURL, c.Config.Model, transport)
				if _, err := e.Embed(c.Inputs.Texts); err != nil {
					t.Fatalf("Embed: %v", err)
				}
			default:
				t.Fatalf("unknown client %q", c.Client)
			}

			var want struct {
				Method  string            `json:"method"`
				URL     string            `json:"url"`
				Headers map[string]string `json:"headers"`
				Body    any               `json:"body"`
			}
			if err := json.Unmarshal(c.Expect, &want); err != nil {
				t.Fatalf("unmarshal expected_request: %v", err)
			}

			if want.Method != "POST" {
				t.Fatalf("fixture method = %q, want POST", want.Method)
			}
			if cap.url != want.URL {
				t.Errorf("url = %q, want %q", cap.url, want.URL)
			}
			if !reflect.DeepEqual(cap.headers, want.Headers) {
				t.Errorf("headers = %v, want %v", cap.headers, want.Headers)
			}

			var gotBody any
			if err := json.Unmarshal(cap.body, &gotBody); err != nil {
				t.Fatalf("unmarshal captured body: %v", err)
			}
			if !reflect.DeepEqual(gotBody, want.Body) {
				t.Errorf("body =\n  %#v\nwant\n  %#v", gotBody, want.Body)
			}
		})
	}
}

func TestModelWireResponses(t *testing.T) {
	var fx wireFixture
	conform.Case(t, "model_wire.json", &fx)
	if len(fx.Responses) == 0 {
		t.Fatal("no response cases loaded")
	}

	for _, c := range fx.Responses {
		t.Run(c.Name, func(t *testing.T) {
			transport := canned(c.ResponseBody)

			switch c.Client {
			case "openai_chat":
				g := NewOpenAIChatGenerator("https://api.example.com/v1", "m", 0.0, nil, transport)
				got, err := g.Answer("q", "p", "en")
				if err != nil {
					t.Fatalf("Answer: %v", err)
				}
				var want string
				if err := json.Unmarshal(c.Expected, &want); err != nil {
					t.Fatalf("unmarshal expected: %v", err)
				}
				if got != want {
					t.Errorf("content = %q, want %q", got, want)
				}
			case "anthropic":
				g := NewAnthropicGenerator("", "m", 0.0, DefaultAnthropicMaxTokens, transport)
				got, err := g.Answer("q", "p", "en")
				if err != nil {
					t.Fatalf("Answer: %v", err)
				}
				var want string
				if err := json.Unmarshal(c.Expected, &want); err != nil {
					t.Fatalf("unmarshal expected: %v", err)
				}
				if got != want {
					t.Errorf("text = %q, want %q", got, want)
				}
			case "openai_embed":
				e := NewOpenAIEmbedding("https://api.example.com/v1", "m", transport)
				got, err := e.Embed([]string{"a", "b"})
				if err != nil {
					t.Fatalf("Embed: %v", err)
				}
				var want [][]float64
				if err := json.Unmarshal(c.Expected, &want); err != nil {
					t.Fatalf("unmarshal expected: %v", err)
				}
				if !reflect.DeepEqual(got, want) {
					t.Errorf("vectors = %v, want %v", got, want)
				}
			default:
				t.Fatalf("unknown client %q", c.Client)
			}
		})
	}
}
