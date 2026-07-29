package main

import (
	"bytes"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"runtime"
	"strings"
)

type client struct {
	baseURL      string
	accessToken  string
	refreshToken string
	http         *http.Client
}

type credentials struct {
	AccessToken  string `json:"access_token"`
	RefreshToken string `json:"refresh_token"`
}

const cliCallbackAddress = "localhost:4444"

type page struct {
	Slug          string `json:"slug"`
	Title         string `json:"title"`
	Content       string `json:"content"`
	ContentFormat string `json:"content_format"`
	Layout        string `json:"layout"`
	IsPublic      bool   `json:"is_public"`
}

type pageList struct {
	Pages []page `json:"pages"`
}

func main() {
	if len(os.Args) < 2 {
		usage()
	}

	c := client{
		baseURL:     strings.TrimRight(envOr("4ORM_URL", "https://4orm.harrhy.xyz"), "/"),
		accessToken: os.Getenv("4ORM_TOKEN"),
		http:        http.DefaultClient,
	}
	if c.accessToken == "" {
		stored := loadCredentials()
		c.accessToken = stored.AccessToken
		c.refreshToken = stored.RefreshToken
	}

	var err error
	switch os.Args[1] {
	case "login":
		err = c.login()
	case "whoami":
		err = c.whoami()
	case "page":
		err = c.pageCommand(os.Args[2:])
	case "media":
		err = c.mediaCommand(os.Args[2:])
	case "help", "-h", "--help":
		usage()
	default:
		usage()
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "4orm:", err)
		os.Exit(1)
	}
}

func (c client) pageCommand(args []string) error {
	if len(args) == 0 {
		return errors.New("usage: 4orm page <list|publish|delete>")
	}
	switch args[0] {
	case "list":
		return c.listPages()
	case "publish":
		return c.publishPage(args[1:])
	case "delete":
		return c.deletePage(args[1:])
	default:
		return fmt.Errorf("unknown page command %q", args[0])
	}
}

func (c client) publishPage(args []string) error {
	flags := flag.NewFlagSet("page publish", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	slug := flags.String("slug", "", "page slug (defaults to the filename)")
	title := flags.String("title", "", "page title (defaults to the filename)")
	format := flags.String("format", "", "content format: html or markdown")
	layout := flags.String("layout", "default", "page layout")
	if err := flags.Parse(args); err != nil {
		return err
	}
	if flags.NArg() != 1 {
		return errors.New("usage: 4orm page publish [flags] <file>")
	}

	filename := flags.Arg(0)
	contentBytes, err := os.ReadFile(filename)
	if err != nil {
		return err
	}
	ext := strings.ToLower(filepath.Ext(filename))
	if *format == "" {
		switch ext {
		case ".md", ".markdown":
			*format = "markdown"
		default:
			*format = "html"
		}
	}
	if *slug == "" {
		*slug = slugFromFilename(filename)
	}
	if *title == "" {
		*title = titleFromSlug(*slug)
	}

	body := page{
		Title:         *title,
		Content:       string(contentBytes),
		ContentFormat: *format,
		Layout:        *layout,
		IsPublic:      true,
	}
	var result page
	if err := c.doJSON(http.MethodPut, "/api/v1/pages/"+url.PathEscape(*slug), body, &result); err != nil {
		return err
	}
	fmt.Printf("published %s (%s)\n", result.Slug, result.Title)
	return nil
}

func (c client) listPages() error {
	var result pageList
	if err := c.doJSON(http.MethodGet, "/api/v1/pages", nil, &result); err != nil {
		return err
	}
	for _, p := range result.Pages {
		fmt.Printf("%-24s %s\n", p.Slug, p.Title)
	}
	return nil
}

func (c client) deletePage(args []string) error {
	if len(args) != 1 {
		return errors.New("usage: 4orm page delete <slug>")
	}
	if err := c.doJSON(http.MethodDelete, "/api/v1/pages/"+url.PathEscape(args[0]), nil, nil); err != nil {
		return err
	}
	fmt.Println("deleted", args[0])
	return nil
}

func (c client) mediaCommand(args []string) error {
	if len(args) != 2 || args[0] != "upload" {
		return errors.New("usage: 4orm media upload <file>")
	}
	file, err := os.Open(args[1])
	if err != nil {
		return err
	}
	defer file.Close()

	var body bytes.Buffer
	writer := multipart.NewWriter(&body)
	part, err := writer.CreateFormFile("file", filepath.Base(args[1]))
	if err != nil {
		return err
	}
	if _, err := io.Copy(part, file); err != nil {
		return err
	}
	if err := writer.Close(); err != nil {
		return err
	}

	var result map[string]any
	if err := c.do(http.MethodPost, "/api/v1/media", &body, writer.FormDataContentType(), &result); err != nil {
		return err
	}
	fmt.Println("uploaded", result["storage_path"])
	return nil
}

func (c client) whoami() error {
	var result struct {
		Username    string `json:"username"`
		DisplayName string `json:"display_name"`
	}
	if err := c.doJSON(http.MethodGet, "/api/v1/me", nil, &result); err != nil {
		return err
	}
	fmt.Printf("%s (%s)\n", result.Username, result.DisplayName)
	return nil
}

func (c client) login() error {
	verifier, err := randomString(32)
	if err != nil {
		return err
	}
	state, err := randomString(24)
	if err != nil {
		return err
	}
	hash := sha256.Sum256([]byte(verifier))
	challenge := base64.RawURLEncoding.EncodeToString(hash[:])
	redirectURI := "http://localhost:4444/auth/cli/callback"

	callback := make(chan string, 1)
	server := &http.Server{Addr: cliCallbackAddress}
	mux := http.NewServeMux()
	mux.HandleFunc("/auth/cli/callback", func(w http.ResponseWriter, req *http.Request) {
		if req.URL.Query().Get("state") != state {
			http.Error(w, "invalid OAuth state", http.StatusBadRequest)
			return
		}
		if oauthError := req.URL.Query().Get("error"); oauthError != "" {
			callback <- "error:" + oauthError
		} else {
			callback <- req.URL.Query().Get("code")
		}
		fmt.Fprintln(w, "4orm login complete. You can close this window.")
	})
	server.Handler = mux
	go func() { _ = server.ListenAndServe() }()
	defer server.Close()

	params := url.Values{
		"response_type":         {"code"},
		"client_id":             {"cli"},
		"redirect_uri":          {redirectURI},
		"scope":                 {"openid profile"},
		"state":                 {state},
		"code_challenge":        {challenge},
		"code_challenge_method": {"S256"},
	}
	authorizeURL := c.baseURL + "/oauth/authorize?" + params.Encode()
	fmt.Println("Open this URL in your browser:")
	fmt.Println(authorizeURL)
	code := <-callback
	if strings.HasPrefix(code, "error:") || code == "" {
		return errors.New("OAuth login was denied")
	}

	form := url.Values{
		"grant_type":    {"authorization_code"},
		"client_id":     {"cli"},
		"redirect_uri":  {redirectURI},
		"code":          {code},
		"code_verifier": {verifier},
	}
	response, err := c.http.PostForm(c.baseURL+"/oauth/token", form)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		data, _ := io.ReadAll(io.LimitReader(response.Body, 4096))
		return fmt.Errorf("token exchange failed: %s", strings.TrimSpace(string(data)))
	}
	var tokenResponse struct {
		AccessToken  string `json:"access_token"`
		RefreshToken string `json:"refresh_token"`
	}
	if err := json.NewDecoder(response.Body).Decode(&tokenResponse); err != nil {
		return err
	}
	if tokenResponse.AccessToken == "" {
		return errors.New("token response did not contain an access token")
	}
	if tokenResponse.RefreshToken == "" {
		return errors.New("token response did not contain a refresh token")
	}
	if err := saveCredentials(credentials{
		AccessToken:  tokenResponse.AccessToken,
		RefreshToken: tokenResponse.RefreshToken,
	}); err != nil {
		return err
	}
	c.accessToken = tokenResponse.AccessToken
	c.refreshToken = tokenResponse.RefreshToken
	fmt.Println("logged in")
	return nil
}

func (c client) doJSON(method, path string, input, output any) error {
	var body io.Reader
	if input != nil {
		encoded, err := json.Marshal(input)
		if err != nil {
			return err
		}
		body = bytes.NewReader(encoded)
	}
	return c.do(method, path, body, "application/json", output)
}

func (c client) do(method, path string, body io.Reader, contentType string, output any) error {
	if c.accessToken == "" {
		return errors.New("not logged in; run `4orm login` first")
	}
	var bodyBytes []byte
	if body != nil {
		var err error
		bodyBytes, err = io.ReadAll(body)
		if err != nil {
			return err
		}
	}
	return c.doWithToken(method, path, bodyBytes, contentType, output, true)
}

func (c client) doWithToken(method, path string, body []byte, contentType string, output any, allowRefresh bool) error {
	var requestBody io.Reader
	if body != nil {
		requestBody = bytes.NewReader(body)
	}
	req, err := http.NewRequest(method, c.baseURL+path, requestBody)
	if err != nil {
		return err
	}
	req.Header.Set("Accept", "application/json")
	req.Header.Set("Authorization", "Bearer "+c.accessToken)
	if contentType != "" {
		req.Header.Set("Content-Type", contentType)
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode == http.StatusUnauthorized && allowRefresh && c.refreshToken != "" {
		io.Copy(io.Discard, resp.Body)
		if err := c.refresh(); err == nil {
			return c.doWithToken(method, path, body, contentType, output, false)
		}
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		data, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		return fmt.Errorf("server returned %s: %s", resp.Status, strings.TrimSpace(string(data)))
	}
	if output == nil {
		return nil
	}
	return json.NewDecoder(resp.Body).Decode(output)
}

func (c *client) refresh() error {
	form := url.Values{
		"grant_type":    {"refresh_token"},
		"client_id":     {"cli"},
		"refresh_token": {c.refreshToken},
	}
	response, err := c.http.PostForm(c.baseURL+"/oauth/token", form)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return fmt.Errorf("refresh failed with %s", response.Status)
	}
	var tokenResponse credentials
	if err := json.NewDecoder(response.Body).Decode(&tokenResponse); err != nil {
		return err
	}
	if tokenResponse.AccessToken == "" || tokenResponse.RefreshToken == "" {
		return errors.New("refresh response did not contain both tokens")
	}
	if err := saveCredentials(tokenResponse); err != nil {
		return err
	}
	c.accessToken = tokenResponse.AccessToken
	c.refreshToken = tokenResponse.RefreshToken
	return nil
}

func slugFromFilename(filename string) string {
	stem := strings.TrimSuffix(filepath.Base(filename), filepath.Ext(filename))
	return strings.ToLower(strings.ReplaceAll(strings.ReplaceAll(stem, " ", "-"), "_", "-"))
}

func titleFromSlug(slug string) string {
	words := strings.FieldsFunc(slug, func(r rune) bool { return r == '-' || r == '_' })
	for i, word := range words {
		if len(word) > 0 {
			words[i] = strings.ToUpper(word[:1]) + word[1:]
		}
	}
	return strings.Join(words, " ")
}

func envOr(name, fallback string) string {
	if value := os.Getenv(name); value != "" {
		return value
	}
	return fallback
}

func randomString(size int) (string, error) {
	data := make([]byte, size)
	if _, err := rand.Read(data); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(data), nil
}

func configPath() string {
	if dir := os.Getenv("XDG_CONFIG_HOME"); dir != "" {
		return filepath.Join(dir, "4orm", "config.json")
	}
	if home, err := os.UserHomeDir(); err == nil {
		if os.Getenv("APPDATA") != "" {
			return filepath.Join(os.Getenv("APPDATA"), "4orm", "config.json")
		}
		if runtime.GOOS == "darwin" {
			return filepath.Join(home, "Library", "Application Support", "4orm", "config.json")
		}
		return filepath.Join(home, ".config", "4orm", "config.json")
	}
	return ""
}

func loadCredentials() credentials {
	path := configPath()
	if path == "" {
		return credentials{}
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return credentials{}
	}
	var result credentials
	if json.Unmarshal(data, &result) != nil {
		return credentials{}
	}
	return result
}

func saveCredentials(value credentials) error {
	path := configPath()
	if path == "" {
		return errors.New("could not determine config directory")
	}
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return err
	}
	data, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(path, append(data, '\n'), 0600)
}

func usage() {
	fmt.Fprintln(os.Stderr, `usage:
  4orm login
  4orm whoami
  4orm page list
  4orm page publish [--slug SLUG] [--title TITLE] FILE
  4orm page delete SLUG
  4orm media upload FILE

environment:
  4ORM_URL    API base URL (default: https://4orm.harrhy.xyz)
  4ORM_TOKEN  OAuth bearer token`)
	os.Exit(2)
}
