package main

import (
	"net/http"
	"net/http/httptest"
	"net/url"
	"testing"
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
