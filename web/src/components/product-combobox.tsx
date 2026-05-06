"use client";

import { useEffect, useRef, useState } from "react";
import { z } from "zod";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { type Product, productSchema } from "@/lib/schemas";
import { cn } from "@/lib/utils";

const resultsSchema = z.array(productSchema);

async function fetchSearch(q: string, signal: AbortSignal): Promise<Product[]> {
  const res = await fetch(`/api/products/search?q=${encodeURIComponent(q)}&limit=20`, {
    signal,
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`search failed: ${res.status}`);
  }
  return resultsSchema.parse(await res.json());
}

export function ProductCombobox({
  inputId,
  value,
  onChange,
}: {
  inputId: string;
  value: string;
  onChange: (sku: string) => void;
}): React.ReactElement {
  const [query, setQuery] = useState(value);
  const [results, setResults] = useState<Product[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const ctrl = new AbortController();
    const t = setTimeout(() => {
      setLoading(true);
      fetchSearch(query, ctrl.signal)
        .then((rows) => setResults(rows))
        .catch((e) => {
          if (e.name !== "AbortError") setResults([]);
        })
        .finally(() => setLoading(false));
    }, 180);
    return () => {
      clearTimeout(t);
      ctrl.abort();
    };
  }, [query, open]);

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (!containerRef.current?.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  function pick(p: Product): void {
    onChange(p.sku);
    setQuery(p.sku);
    setOpen(false);
  }

  return (
    <div className="space-y-1.5" ref={containerRef}>
      <Label htmlFor={inputId} className="text-xs">
        Override SKU — search the product master
      </Label>
      <Input
        id={inputId}
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          onChange(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        placeholder="Search by SKU or description"
        className="font-mono"
        autoComplete="off"
      />
      {open ? (
        <div className="max-h-64 w-full overflow-auto rounded-md border border-input bg-popover shadow-sm">
          {loading && results.length === 0 ? (
            <div className="px-3 py-2 text-xs text-muted-foreground">Searching…</div>
          ) : results.length === 0 ? (
            <div className="px-3 py-2 text-xs text-muted-foreground">No matches</div>
          ) : (
            <ul className="py-1 text-sm">
              {results.map((p) => (
                <li key={p.sku}>
                  <button
                    type="button"
                    onClick={() => pick(p)}
                    className={cn(
                      "flex w-full flex-col items-start gap-0.5 px-3 py-1.5 text-left",
                      "hover:bg-accent hover:text-accent-foreground",
                      p.sku === value ? "bg-accent/40" : "",
                    )}
                  >
                    <span className="font-mono text-xs">{p.sku}</span>
                    <span className="text-xs text-muted-foreground">
                      {p.description}
                      {p.pack_size ? ` · ${p.pack_size}` : ""} · {p.uom}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  );
}
