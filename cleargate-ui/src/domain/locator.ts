export interface Locator {
  part?: string;
  page?: number;
  slide?: number;
  shape_id?: number | string;
  paragraph_index?: number;
  table?: number;
  row?: number;
  col?: number;
  bbox?: [number, number, number, number] | number[];
  image_ref?: string;
}

export function formatLocator(loc?: Locator): string {
  if (!loc) return '-';
  const parts: string[] = [];

  if (loc.page !== undefined) {
    parts.push(`Page ${loc.page}`);
  }
  if (loc.slide !== undefined) {
    let s = `Slide ${loc.slide}`;
    if (loc.shape_id !== undefined) {
      s += ` · shape ${loc.shape_id}`;
    }
    parts.push(s);
  } else if (loc.shape_id !== undefined) {
    parts.push(`Shape ${loc.shape_id}`);
  }

  if (loc.table !== undefined) {
    let t = `Table ${loc.table}`;
    if (loc.row !== undefined) t += ` · row ${loc.row}`;
    if (loc.col !== undefined) t += ` · col ${loc.col}`;
    parts.push(t);
  } else {
    if (loc.row !== undefined && loc.col !== undefined) {
      parts.push(`Row ${loc.row} · Col ${loc.col}`);
    }
  }

  if (loc.paragraph_index !== undefined) {
    parts.push(`¶ ${loc.paragraph_index}`);
  }

  if (loc.image_ref) {
    parts.push(`Image: ${loc.image_ref}`);
  }

  if (parts.length === 0 && loc.part) {
    return loc.part;
  }

  return parts.length > 0 ? parts.join(' · ') : '-';
}
