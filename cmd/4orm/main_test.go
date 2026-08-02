package main

import (
	"encoding/json"
	"testing"
)

func TestSlugFromFilename(t *testing.T) {
	if got := slugFromFilename("notes/my travel_notes.md"); got != "my-travel-notes" {
		t.Fatalf("slugFromFilename() = %q", got)
	}
}

func TestTitleFromSlug(t *testing.T) {
	if got := titleFromSlug("my-travel-notes"); got != "My Travel Notes" {
		t.Fatalf("titleFromSlug() = %q", got)
	}
}

func TestPageWriteRequestOmitsSlug(t *testing.T) {
	data, err := json.Marshal(pageWriteRequest{
		Title:         "About",
		Content:       "<h1>Hello</h1>",
		ContentFormat: "html",
		Layout:        "default",
		IsPublic:      true,
	})
	if err != nil {
		t.Fatal(err)
	}
	var body map[string]any
	if err := json.Unmarshal(data, &body); err != nil {
		t.Fatal(err)
	}
	if _, ok := body["slug"]; ok {
		t.Fatalf("publish request unexpectedly contains slug: %s", data)
	}
	if body["title"] != "About" || body["content_format"] != "html" || body["layout"] != "default" || body["is_public"] != true {
		t.Fatalf("publish request missing expected fields: %s", data)
	}
}

func TestMediaListResponse(t *testing.T) {
	var result mediaList
	if err := json.Unmarshal([]byte(`{"items":[{"id":7,"storage_path":"testuser/photo.png","mime_type":"image/png","size_bytes":42}],"storage_used":42,"storage_limit":100,"storage_pct":42}`), &result); err != nil {
		t.Fatal(err)
	}
	if len(result.Items) != 1 || result.Items[0].ID != 7 || result.StoragePct != 42 {
		t.Fatalf("unexpected media response: %+v", result)
	}
}

func TestCLIVersion(t *testing.T) {
	if cliVersion != "0.2.0" {
		t.Fatalf("cliVersion = %q", cliVersion)
	}
}
