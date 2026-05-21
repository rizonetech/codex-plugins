// Prometheus-text metrics primitives. Zero deps.
//
// Implements only what auth-proxy.js needs: Counter, Gauge, and Histogram
// (with fixed default buckets). Label cardinality is the caller's
// responsibility — there's no built-in cap. Per-tool labels for MCP are
// expected to stay small (~10s of unique tools), well within Prometheus's
// recommended cardinality limits.

'use strict';

function escapeLabelValue(v) {
  // Per Prometheus exposition format: backslash, double-quote, and newline
  // need escaping inside label values.
  return String(v)
    .replace(/\\/g, '\\\\')
    .replace(/"/g, '\\"')
    .replace(/\n/g, '\\n');
}

function escapeHelp(s) {
  return String(s).replace(/\\/g, '\\\\').replace(/\n/g, '\\n');
}

function labelString(labels) {
  if (!labels) return '';
  const keys = Object.keys(labels).sort();
  if (keys.length === 0) return '';
  const parts = keys.map((k) => `${k}="${escapeLabelValue(labels[k])}"`);
  return `{${parts.join(',')}}`;
}

function labelKey(labels) {
  if (!labels) return '';
  const keys = Object.keys(labels).sort();
  return keys.map((k) => `${k}=${labels[k]}`).join('|');
}

class Counter {
  constructor(name, help, labelNames = []) {
    this.name = name;
    this.help = help;
    this.labelNames = labelNames;
    this.values = new Map(); // labelKey -> { labels, value }
  }
  inc(labels = {}, amount = 1) {
    const k = labelKey(labels);
    const cur = this.values.get(k);
    if (cur) cur.value += amount;
    else this.values.set(k, { labels, value: amount });
  }
  get(labels = {}) {
    const cur = this.values.get(labelKey(labels));
    return cur ? cur.value : 0;
  }
  serialize() {
    const lines = [
      `# HELP ${this.name} ${escapeHelp(this.help)}`,
      `# TYPE ${this.name} counter`,
    ];
    if (this.values.size === 0) {
      lines.push(`${this.name} 0`);
    } else {
      for (const { labels, value } of this.values.values()) {
        lines.push(`${this.name}${labelString(labels)} ${value}`);
      }
    }
    return lines.join('\n');
  }
}

class Gauge {
  constructor(name, help, labelNames = []) {
    this.name = name;
    this.help = help;
    this.labelNames = labelNames;
    this.values = new Map();
    this._dynamic = null; // optional: () => Map<labelKey, {labels, value}>
  }
  set(labels, value) {
    if (typeof labels === 'number' && value === undefined) { value = labels; labels = {}; }
    const k = labelKey(labels);
    this.values.set(k, { labels, value });
  }
  inc(labels = {}, amount = 1) {
    const k = labelKey(labels);
    const cur = this.values.get(k);
    if (cur) cur.value += amount;
    else this.values.set(k, { labels, value: amount });
  }
  dec(labels = {}, amount = 1) { this.inc(labels, -amount); }
  // Allow a gauge backed by a live function (refreshed at scrape time).
  bindDynamic(fn) { this._dynamic = fn; }
  serialize() {
    let entries;
    if (this._dynamic) {
      entries = this._dynamic();
    } else {
      entries = Array.from(this.values.values());
    }
    const lines = [
      `# HELP ${this.name} ${escapeHelp(this.help)}`,
      `# TYPE ${this.name} gauge`,
    ];
    if (!entries || entries.length === 0) {
      lines.push(`${this.name} 0`);
    } else {
      for (const { labels, value } of entries) {
        lines.push(`${this.name}${labelString(labels)} ${value}`);
      }
    }
    return lines.join('\n');
  }
}

const DEFAULT_BUCKETS = [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10];

class Histogram {
  constructor(name, help, labelNames = [], buckets = DEFAULT_BUCKETS) {
    this.name = name;
    this.help = help;
    this.labelNames = labelNames;
    this.buckets = buckets.slice().sort((a, b) => a - b);
    this.values = new Map(); // labelKey -> { labels, counts: [], sum, count }
  }
  observe(labels, value) {
    if (typeof labels === 'number' && value === undefined) { value = labels; labels = {}; }
    const k = labelKey(labels);
    let entry = this.values.get(k);
    if (!entry) {
      entry = {
        labels,
        counts: new Array(this.buckets.length).fill(0),
        sum: 0,
        count: 0,
      };
      this.values.set(k, entry);
    }
    for (let i = 0; i < this.buckets.length; i++) {
      if (value <= this.buckets[i]) entry.counts[i] += 1;
    }
    entry.sum += value;
    entry.count += 1;
  }
  serialize() {
    const lines = [
      `# HELP ${this.name} ${escapeHelp(this.help)}`,
      `# TYPE ${this.name} histogram`,
    ];
    if (this.values.size === 0) {
      // Emit a zero-count series so scrapers see the metric exists.
      for (const b of this.buckets) {
        lines.push(`${this.name}_bucket{le="${b}"} 0`);
      }
      lines.push(`${this.name}_bucket{le="+Inf"} 0`);
      lines.push(`${this.name}_sum 0`);
      lines.push(`${this.name}_count 0`);
    } else {
      for (const { labels, counts, sum, count } of this.values.values()) {
        const baseLabels = Object.keys(labels);
        for (let i = 0; i < this.buckets.length; i++) {
          const lbl = Object.assign({}, labels, { le: String(this.buckets[i]) });
          lines.push(`${this.name}_bucket${labelString(lbl)} ${counts[i]}`);
        }
        const infLbl = Object.assign({}, labels, { le: '+Inf' });
        lines.push(`${this.name}_bucket${labelString(infLbl)} ${count}`);
        const sumLabels = baseLabels.length ? labelString(labels) : '';
        lines.push(`${this.name}_sum${sumLabels} ${sum}`);
        lines.push(`${this.name}_count${sumLabels} ${count}`);
      }
    }
    return lines.join('\n');
  }
}

class Registry {
  constructor() { this.metrics = []; }
  register(m) { this.metrics.push(m); return m; }
  counter(name, help, labelNames)   { return this.register(new Counter(name, help, labelNames)); }
  gauge(name, help, labelNames)     { return this.register(new Gauge(name, help, labelNames)); }
  histogram(name, help, labelNames) { return this.register(new Histogram(name, help, labelNames)); }
  serialize() {
    return this.metrics.map((m) => m.serialize()).join('\n') + '\n';
  }
}

module.exports = { Registry, Counter, Gauge, Histogram, DEFAULT_BUCKETS };
