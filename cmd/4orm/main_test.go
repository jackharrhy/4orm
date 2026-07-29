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
