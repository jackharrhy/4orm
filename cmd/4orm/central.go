package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"

	"github.com/coreos/go-oidc/v3/oidc"
)

type authConfiguration struct {
	Issuer   string   `json:"issuer"`
	ClientID string   `json:"client_id"`
	Scopes   []string `json:"scopes"`
}

func (c client) identityProvider(ctx context.Context) (authConfiguration, *oidc.Provider, error) {
	var configuration authConfiguration
	response, err := c.http.Get(c.baseURL + "/api/v1/auth-config")
	if err != nil {
		return configuration, nil, err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return configuration, nil, errors.New("central API login is unavailable")
	}
	if err := json.NewDecoder(io.LimitReader(response.Body, 65536)).Decode(&configuration); err != nil {
		return configuration, nil, err
	}
	if configuration.Issuer != "https://auth.jackharrhy.dev" || configuration.ClientID == "" {
		return configuration, nil, errors.New("invalid central identity configuration")
	}
	transport := *c.http
	transport.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	ctx = oidc.ClientContext(ctx, &transport)
	provider, err := oidc.NewProvider(ctx, configuration.Issuer)
	if err != nil {
		return configuration, nil, errors.New("central identity discovery failed")
	}
	var endpoints struct {
		Authorization string `json:"authorization_endpoint"`
		Token         string `json:"token_endpoint"`
		Keys          string `json:"jwks_uri"`
	}
	if err := provider.Claims(&endpoints); err != nil {
		return configuration, nil, err
	}
	for _, endpoint := range []string{endpoints.Authorization, endpoints.Token, endpoints.Keys} {
		parsed, err := url.Parse(endpoint)
		if err != nil || parsed.Scheme != "https" || parsed.Host != "auth.jackharrhy.dev" || parsed.User != nil || parsed.Fragment != "" {
			return configuration, nil, errors.New("identity endpoint outside the central issuer")
		}
	}
	return configuration, provider, nil
}

func (c client) exchangeCentral(endpoint string, form url.Values) (credentials, string, error) {
	var result struct {
		credentials
		IDToken string `json:"id_token"`
	}
	// A token request must never forward credentials through an HTTP redirect.
	transport := *c.http
	transport.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	response, err := transport.PostForm(endpoint, form)
	if err != nil {
		return credentials{}, "", errors.New("central token request failed")
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return credentials{}, "", fmt.Errorf("central token request returned %s; run 4orm login", response.Status)
	}
	if err := json.NewDecoder(io.LimitReader(response.Body, 131072)).Decode(&result); err != nil {
		return credentials{}, "", errors.New("invalid central token response")
	}
	if result.AccessToken == "" || result.RefreshToken == "" {
		return credentials{}, "", errors.New("central response is missing access or refresh token")
	}
	return result.credentials, result.IDToken, nil
}

func verifyCentralIdentity(ctx context.Context, provider *oidc.Provider, clientID, rawToken, nonce string) error {
	identity, err := provider.Verifier(&oidc.Config{ClientID: clientID, SupportedSigningAlgs: []string{"RS256"}}).Verify(ctx, rawToken)
	if err != nil || identity.Nonce != nonce || identity.Subject == "" {
		return errors.New("central identity verification failed")
	}
	var claims struct {
		AuthorizedParty string `json:"azp"`
	}
	if err := identity.Claims(&claims); err != nil {
		return errors.New("invalid central identity claims")
	}
	if (len(identity.Audience) > 1 || claims.AuthorizedParty != "") && claims.AuthorizedParty != clientID {
		return errors.New("central identity authorized party mismatch")
	}
	return nil
}

func (c *client) refresh() error {
	if c.issuer == "" || c.clientID == "" {
		return errors.New("legacy credentials require a new sign-in; run 4orm login")
	}
	ctx, cancel := context.WithTimeout(context.Background(), c.http.Timeout)
	defer cancel()
	configuration, provider, err := c.identityProvider(ctx)
	if err != nil {
		return err
	}
	if c.issuer != configuration.Issuer || c.clientID != configuration.ClientID {
		return errors.New("saved credentials belong to a different issuer or client; run 4orm login")
	}
	updated, _, err := c.exchangeCentral(provider.Endpoint().TokenURL, url.Values{
		"grant_type": {"refresh_token"}, "client_id": {configuration.ClientID}, "refresh_token": {c.refreshToken},
	})
	if err != nil {
		return err
	}
	updated.Issuer, updated.ClientID = configuration.Issuer, configuration.ClientID
	if err := saveCredentials(updated); err != nil {
		return err
	}
	c.accessToken, c.refreshToken = updated.AccessToken, updated.RefreshToken
	return nil
}
