package main

import (
	"context"
	"crypto"
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"maps"
	"net/http"
	"net/http/httptest"
	"net/url"
	"testing"
	"time"

	"github.com/coreos/go-oidc/v3/oidc"
)

func TestLegacyRefreshNeverLeavesClient(t *testing.T) {
	requests := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests++
	}))
	defer server.Close()
	c := client{baseURL: server.URL, http: server.Client(), refreshToken: "legacy-private"}
	if err := c.refresh(); err == nil {
		t.Fatal("legacy refresh must require a new login")
	}
	if requests != 0 {
		t.Fatal("legacy credentials caused an outbound request")
	}
}

func TestCentralIdentityRejectsInvalidSignatureAndClaims(t *testing.T) {
	key, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatal(err)
	}
	keys := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode(map[string]any{"keys": []any{map[string]any{
			"kty": "RSA", "kid": "key", "use": "sig", "alg": "RS256",
			"n": base64.RawURLEncoding.EncodeToString(key.N.Bytes()), "e": "AQAB",
		}}})
	}))
	defer keys.Close()
	ctx := context.Background()
	provider := (&oidc.ProviderConfig{IssuerURL: "https://auth.jackharrhy.dev", JWKSURL: keys.URL}).NewProvider(ctx)
	claims := map[string]any{
		"iss": "https://auth.jackharrhy.dev", "sub": "subject", "aud": "cli", "nonce": "nonce",
		"exp": time.Now().Add(time.Minute).Unix(), "iat": time.Now().Unix(),
	}
	sign := func(values map[string]any, signer *rsa.PrivateKey) string {
		header := base64.RawURLEncoding.EncodeToString([]byte(`{"alg":"RS256","kid":"key"}`))
		body, err := json.Marshal(values)
		if err != nil {
			t.Fatal(err)
		}
		message := header + "." + base64.RawURLEncoding.EncodeToString(body)
		digest := sha256.Sum256([]byte(message))
		signature, err := rsa.SignPKCS1v15(rand.Reader, signer, crypto.SHA256, digest[:])
		if err != nil {
			t.Fatal(err)
		}
		return message + "." + base64.RawURLEncoding.EncodeToString(signature)
	}
	if err := verifyCentralIdentity(ctx, provider, "cli", sign(claims, key), "nonce"); err != nil {
		t.Fatal(err)
	}
	for _, changed := range []map[string]any{
		{"iss": "https://other.example"}, {"aud": "other"}, {"nonce": "wrong"},
		{"exp": int64(1)}, {"sub": ""}, {"azp": "other"}, {"aud": []string{"cli", "other"}},
	} {
		values := maps.Clone(claims)
		maps.Copy(values, changed)
		if err := verifyCentralIdentity(ctx, provider, "cli", sign(values, key), "nonce"); err == nil {
			t.Fatal("invalid signed identity was accepted")
		}
	}
	otherKey, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatal(err)
	}
	if err := verifyCentralIdentity(ctx, provider, "cli", sign(claims, otherKey), "nonce"); err == nil {
		t.Fatal("invalid signature was accepted")
	}
}

func TestCentralTokenExchangeDoesNotFollowRedirect(t *testing.T) {
	forwarded := false
	target := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		forwarded = true
	}))
	defer target.Close()
	source := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, target.URL, http.StatusTemporaryRedirect)
	}))
	defer source.Close()
	c := client{http: source.Client()}
	_, _, err := c.exchangeCentral(source.URL, url.Values{"refresh_token": {"private"}})
	if err == nil || forwarded {
		t.Fatal("token redirect must fail without forwarding credentials")
	}
}
