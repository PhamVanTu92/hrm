/** Shapes matching the backend response envelope (see app/core/pagination.py). */

export interface Envelope<T> {
  data: T;
}

export interface PageMeta {
  page: number;
  size: number;
  total: number;
  pages: number;
}

export interface Page<T> {
  data: T[];
  meta: PageMeta;
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
  };
}

export interface PageQuery {
  page?: number;
  size?: number;
  sort?: string;
}
