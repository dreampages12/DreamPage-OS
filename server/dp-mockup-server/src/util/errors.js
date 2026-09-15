export class HttpError extends Error {
  constructor(status, code, message, details) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export const badRequest = (code, msg, details) => new HttpError(400, code, msg, details);
export const notFound = (code, msg) => new HttpError(404, code, msg);
export const conflict = (code, msg, details) => new HttpError(409, code, msg, details);
export const unavailable = (code, msg, details) => new HttpError(503, code, msg, details);
export const internal = (code, msg, details) => new HttpError(500, code, msg, details);

/** Semafor: begrenser hvor mange oppgaver som kjører samtidig. */
export class Semaphore {
  constructor(limit) {
    this.limit = Math.max(1, limit);
    this.active = 0;
    this.queue = [];
  }

  async run(fn) {
    if (this.active >= this.limit) {
      await new Promise((resolve) => this.queue.push(resolve));
    }
    this.active += 1;
    try {
      return await fn();
    } finally {
      this.active -= 1;
      const next = this.queue.shift();
      if (next) next();
    }
  }

  get depth() {
    return this.queue.length;
  }
}

export function withTimeout(promise, ms, code, msg) {
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new HttpError(504, code, `${msg} (${ms} ms)`)), ms);
  });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}
