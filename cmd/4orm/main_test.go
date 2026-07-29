package main

import "testing"

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
