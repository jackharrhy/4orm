package main

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
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
	if cliVersion != "0.3.0" {
		t.Fatalf("cliVersion = %q", cliVersion)
	}
}

func TestParseCLIVersion(t *testing.T) {
	got, err := parseCLIVersion("cli-v12.3.4")
	if err != nil || got != [3]int{12, 3, 4} {
		t.Fatalf("parseCLIVersion() = %v, %v", got, err)
	}
	if _, err := parseCLIVersion("cli-v1.2"); err == nil {
		t.Fatal("parseCLIVersion() accepted an incomplete version")
	}
}

func TestVerifyChecksum(t *testing.T) {
	data := []byte("release archive")
	hash := sha256.Sum256(data)
	checksums := fmt.Sprintf("%s  4orm-linux-amd64.tar.gz\n", hex.EncodeToString(hash[:]))
	if err := verifyChecksum(data, "4orm-linux-amd64.tar.gz", []byte(checksums)); err != nil {
		t.Fatal(err)
	}
	if err := verifyChecksum([]byte("tampered"), "4orm-linux-amd64.tar.gz", []byte(checksums)); err == nil {
		t.Fatal("verifyChecksum() accepted tampered data")
	}
}

func TestExtractTarGz(t *testing.T) {
	var archive bytes.Buffer
	compressed := gzip.NewWriter(&archive)
	writer := tar.NewWriter(compressed)
	payload := []byte("binary")
	if err := writer.WriteHeader(&tar.Header{Name: "4orm", Mode: 0755, Size: int64(len(payload))}); err != nil {
		t.Fatal(err)
	}
	if _, err := writer.Write(payload); err != nil {
		t.Fatal(err)
	}
	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}
	if err := compressed.Close(); err != nil {
		t.Fatal(err)
	}

	got, err := extractBinary(archive.Bytes(), archiveTarGz)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(got, payload) {
		t.Fatalf("extractBinary() = %q", got)
	}
}
