import "server-only";
import { Pool, types, type PoolClient } from "pg";

// keep DATE columns as 'YYYY-MM-DD' strings (no timezone shifts); numerics as JS numbers
types.setTypeParser(1082, (v) => v);
types.setTypeParser(1700, (v) => (v === null ? null : Number(v)));

const g = globalThis as unknown as { __pgPool?: Pool };

export function pool(): Pool {
  g.__pgPool ??= new Pool({ connectionString: process.env.DATABASE_URL, max: 5 });
  return g.__pgPool;
}

export async function q<T = any>(text: string, params: unknown[] = []): Promise<T[]> {
  return (await pool().query(text, params)).rows as T[];
}

export async function tx<T>(fn: (c: PoolClient) => Promise<T>): Promise<T> {
  const c = await pool().connect();
  try {
    await c.query("begin");
    const out = await fn(c);
    await c.query("commit");
    return out;
  } catch (e) {
    await c.query("rollback");
    throw e;
  } finally {
    c.release();
  }
}
