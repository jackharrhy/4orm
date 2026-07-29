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

type pageWriteRequest struct {
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
		if hasHelpArg(os.Args[2:]) {
			fmt.Println("usage: 4orm login\n\nOpen a browser to sign in and save OAuth credentials locally.")
			return
		}
		err = c.login()
	case "whoami":
		if hasHelpArg(os.Args[2:]) {
			fmt.Println("usage: 4orm whoami\n\nShow the currently authenticated account.")
			return
		}
		err = c.whoami()
	case "page":
		err = c.pageCommand(os.Args[2:])
	case "media":
		err = c.mediaCommand(os.Args[2:])
	case "help", "-h", "--help":
		printUsage(os.Stdout)
		return
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
		printPageUsage(os.Stderr)
		return nil
	}
	if args[0] == "-h" || args[0] == "--help" {
		printPageUsage(os.Stdout)
		return nil
	}
	switch args[0] {
	case "list":
		if len(args) > 1 {
			if hasHelpArg(args[1:]) {
				fmt.Println("usage: 4orm page list\n\nList pages belonging to the authenticated account.")
				return nil
			}
			return errors.New("usage: 4orm page list")
		}
		return c.listPages()
	case "publish":
		return c.publishPage(args[1:])
	case "delete":
		return c.deletePage(args[1:])
	default:
		return fmt.Errorf("unknown page command %q; run `4orm page --help`", args[0])
	}
}

func (c client) publishPage(args []string) error {
	flags := flag.NewFlagSet("page publish", flag.ContinueOnError)
	flags.SetOutput(os.Stdout)
	flags.Usage = func() { printPublishUsage(os.Stdout) }
	slug := flags.String("slug", "", "page slug (defaults to the filename)")
	title := flags.String("title", "", "page title (defaults to the filename)")
	format := flags.String("format", "", "content format: html or markdown (default: inferred from extension)")
	layout := flags.String("layout", "default", "page layout: default, simple, cssonly, or raw")
	if err := flags.Parse(args); err != nil {
		if err == flag.ErrHelp {
			return nil
		}
		return err
	}
	if flags.NArg() != 1 {
		return errors.New("usage: 4orm page publish [flags] <file>; run `4orm page publish --help`")
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

	body := pageWriteRequest{
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
	if len(args) == 1 && (args[0] == "-h" || args[0] == "--help") {
		fmt.Println("usage: 4orm page delete <slug>\n\nDelete a published page by its slug.")
		return nil
	}
	if len(args) != 1 {
		return errors.New("usage: 4orm page delete <slug>; run `4orm page --help`")
	}
	if err := c.doJSON(http.MethodDelete, "/api/v1/pages/"+url.PathEscape(args[0]), nil, nil); err != nil {
		return err
	}
	fmt.Println("deleted", args[0])
	return nil
}

func (c client) mediaCommand(args []string) error {
	if hasHelpArg(args) {
		printMediaUsage(os.Stdout)
		return nil
	}
	if len(args) != 2 || args[0] != "upload" {
		return errors.New("usage: 4orm media upload <file>; run `4orm media --help`")
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

func hasHelpArg(args []string) bool {
	for _, arg := range args {
		if arg == "-h" || arg == "--help" {
			return true
		}
	}
	return false
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
	printUsage(os.Stderr)
	os.Exit(2)
}

func printUsage(w io.Writer) {
	fmt.Fprintln(w, `4orm is a command-line client for publishing pages and uploading media to 4orm.

usage:
  4orm login                         Sign in through the browser using OAuth.
  4orm whoami                        Show the currently authenticated account.
  4orm page list                     List your published pages.
  4orm page publish [flags] FILE     Publish or replace a page from a file.
  4orm page delete SLUG              Delete a published page.
  4orm media upload FILE             Upload an image or other media file.

page publish:
  The slug defaults to the filename without its extension. The title defaults
  to the slug with hyphens and underscores converted to spaces and title case.
  HTML is sent as-is. Markdown is rendered by 4orm before the page is shown.

  Formats: html, markdown
  Layouts:
    default   Normal 4orm page with navigation and the standard content panel.
    simple    Normal page chrome without the content panel wrapper.
    cssonly   Render content with the site's CSS but without normal page chrome.
    raw       Return the rendered content without page chrome; useful for embeds.

  Run '4orm page publish --help' for all publish flags and examples.

environment:
  4ORM_URL    API base URL (default: https://4orm.harrhy.xyz)
  4ORM_TOKEN  OAuth bearer token; otherwise use the token saved by '4orm login'

examples:
  4orm login
  4orm page publish README.md
  4orm page publish --slug about --title "About Me" about.html
  4orm page publish --format markdown --layout simple notes.md
  4orm media upload images/avatar.png`)
}

func printPageUsage(w io.Writer) {
	fmt.Fprintln(w, `usage:
  4orm page list
  4orm page publish [flags] FILE
  4orm page delete SLUG

Commands:
  list       List pages belonging to the authenticated account.
  publish    Create or replace a page using the file contents.
  delete     Delete a page by slug.

Run '4orm page publish --help' for formats, layouts, flags, and examples.`)
}

func printPublishUsage(w io.Writer) {
	fmt.Fprintln(w, `usage: 4orm page publish [flags] FILE

Publish or replace a page. The slug and title are inferred from FILE unless
explicitly provided. The request is authenticated with 4orm login credentials.

flags:
  --slug SLUG       URL slug (default: filename without extension)
  --title TITLE     Page title (default: derived from slug)
  --format FORMAT   html or markdown (default: html, or markdown for .md/.markdown)
  --layout LAYOUT   default, simple, cssonly, or raw (default: default)

layouts:
  default   Standard 4orm navigation and content panel.
  simple    Standard page chrome without the content panel wrapper.
  cssonly   Site CSS with no normal page chrome.
  raw       Rendered content only, without page chrome.

examples:
  4orm page publish index.html
  4orm page publish --slug about --title "About Me" about.html
  4orm page publish --format markdown --layout simple notes.md`)
}

func printMediaUsage(w io.Writer) {
	fmt.Fprintln(w, `usage: 4orm media upload FILE

Upload FILE to 4orm media storage. The resulting storage path is printed after
the upload completes. Use the returned path in page content where appropriate.`)
}
