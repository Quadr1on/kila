// Supabase-Storage-like client for the KILA Local Bucket.
//   storage.from("kb").upload(file)
//   storage.from("kb").list({ prefix: "sops/" })
//   storage.getSignedUrl(objectId, 300)

import { api, apiUrl } from "./api";

export type BucketName = "uploads" | "kb" | "deliverables" | "pid" | "models" | "thumbnails";

export type StoredObject = {
  object_id: string;
  bucket: BucketName;
  path: string;
  sha256: string;
  size: number;
  mime: string;
  original_name: string;
  uploaded_by: number | null;
  created_at: string;
  metadata: Record<string, unknown>;
  thumbnail_url: string | null;
};

export type BucketInfo = { name: BucketName; can_read: boolean; can_write: boolean };

function bucket(name: BucketName) {
  return {
    async upload(file: File, opts: { path?: string } = {}): Promise<StoredObject> {
      const form = new FormData();
      form.append("file", file);
      if (opts.path) form.append("path", opts.path);
      return api<StoredObject>(`/storage/${name}/upload`, { method: "POST", body: form });
    },
    async list(opts: { prefix?: string } = {}): Promise<StoredObject[]> {
      const q = opts.prefix ? `?prefix=${encodeURIComponent(opts.prefix)}` : "";
      return api<StoredObject[]>(`/storage/${name}/list${q}`);
    },
  };
}

export const storage = {
  from: bucket,
  buckets: () => api<BucketInfo[]>("/storage/buckets"),
  meta: (objectId: string) => api<StoredObject>(`/storage/object/${objectId}/meta`),
  remove: (objectId: string) => api<void>(`/storage/object/${objectId}`, { method: "DELETE" }),
  async getSignedUrl(objectId: string, expiresS = 300): Promise<string> {
    const r = await api<{ url: string; expires_at: number }>(
      `/storage/object/${objectId}/signed-url?expires=${expiresS}`,
      { method: "POST" },
    );
    return apiUrl(r.url);
  },
};
