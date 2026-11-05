#!/usr/bin/env node
/**
 * Glossary vocabulary checker.
 * Enforces terminology rules defined in GLOSSARY.md across markdown docs and code.
 *
 * Usage:
 *   node bin/check-glossary.js           # Check all git-tracked files
 *   node bin/check-glossary.js --staged  # Check git-staged files only
 *   node bin/check-glossary.js <file>... # Check specific files
 *
 * Also exports checkContent, findUnboldedTerms and loadGlossaryTerms for tests.
 */

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const REPO_ROOT = path.resolve(__dirname, '..');

// Prohibited terms mapped to preferred vocabulary in GLOSSARY.md
const VOCABULARY_RULES = [
  {
    pattern: /\bground[- ]truth\b/i,
    prohibited: 'ground truth',
    preferred: 'Answer Key',
    section: 'Causes of the Spike'
  },
  {
    pattern: /\bactuals\b/i,
    prohibited: 'actuals',
    preferred: 'Reveal',
    section: 'Modeling'
  },
  {
    pattern: /\bholdout(s)?\b/i,
    prohibited: 'holdout',
    preferred: 'Reveal',
    section: 'Modeling'
  },
  {
    pattern: /\bvalidation[- ]sets?\b/i,
    prohibited: 'validation set',
    preferred: 'Reveal',
    section: 'Modeling'
  },
  {
    pattern: /\bpositive[- ]rates?\b/i,
    prohibited: 'positive rate',
    preferred: 'Positivity',
    section: 'Data'
  },
  {
    pattern: /\bhit[- ]rates?\b/i,
    prohibited: 'hit rate',
    preferred: 'Positivity',
    section: 'Data'
  },
  {
    pattern: /\bfeed[- ]files?\b/i,
    prohibited: 'feed file',
    preferred: 'Hospital Feed',
    section: 'Data'
  },
  {
    pattern: /\bas[- ]of[- ]dates?\b/i,
    prohibited: 'as-of date',
    preferred: 'Cutoff',
    section: 'Data'
  },
  {
    pattern: /\bdata[- ]bugs?\b/i,
    prohibited: 'data bug',
    preferred: 'Pipeline Defect',
    section: 'Causes of the Spike'
  },
  {
    pattern: /\betl[- ]issues?\b/i,
    prohibited: 'ETL issue',
    preferred: 'Pipeline Defect',
    section: 'Causes of the Spike'
  },
  {
    pattern: /\btesting[- ]bias(es)?\b/i,
    prohibited: 'testing bias',
    preferred: 'Sampling Artifact',
    section: 'Causes of the Spike'
  },
  {
    pattern: /\bvolume[- ]effects?\b/i,
    prohibited: 'volume effect',
    preferred: 'Sampling Artifact',
    section: 'Causes of the Spike'
  },
  {
    // Any "baseline <change>" phrase describes the Seasonal Ramp. A bare
    // "baseline" in the statistical sense (a classical ARIMA_PLUS baseline) is
    // fine; its Start Point sense (GLOSSARY.md) is left to human review.
    pattern: /\bbaseline[- ](growths?|trends?|increases?|rises?)\b/i,
    prohibited: 'baseline growth / trend / increase / rise',
    preferred: 'Seasonal Ramp',
    section: 'Causes of the Spike'
  },
  {
    pattern: /\broot[- ]causes?\b/i,
    prohibited: 'root cause',
    preferred: 'Attribution',
    section: 'Causes of the Spike'
  },
  {
    pattern: /\b(chatbots?|copilots?)\b/i,
    prohibited: 'chatbot / copilot',
    preferred: 'Command Center',
    section: 'The harness'
  },
  {
    pattern: /\bdata[- ](simulators?|fakers?)\b/i,
    prohibited: 'data simulator / faker',
    preferred: 'Data Generator',
    section: 'Data'
  }
];

// Files and directories excluded from vocabulary checks
// The presenter run-through where every glossary term in prose must be **bolded**.
const BOLD_REQUIRED_FILES = new Set(['DEMO.md']);

const EXCLUDED_PATHS = new Set([
  'GLOSSARY.md',
  'bin/check-glossary.js',
  'package.json',
  'package-lock.json'
]);

const EXCLUDED_DIR_PREFIXES = [
  'node_modules/',
  '.git/',
  '.husky/',
  '.worktree/',
  '.vscode/',
  '.venv/',
  '__pycache__/',
  'graphify-out/'
];

function isPathExcluded(relPath) {
  const normalized = relPath.replace(/\\/g, '/');
  if (EXCLUDED_PATHS.has(normalized)) return true;
  for (const prefix of EXCLUDED_DIR_PREFIXES) {
    if (normalized.startsWith(prefix) || normalized.includes('/' + prefix)) return true;
  }
  // Exclude binary, image, lock files
  if (/\.(png|jpg|jpeg|gif|ico|pdf|zip|tar|gz|pyc|lock)$/i.test(normalized)) {
    return true;
  }
  return false;
}

function getFilesToCheck(args) {
  if (args.length > 0 && args[0] !== '--staged') {
    return args
      .map(f => path.relative(REPO_ROOT, path.resolve(REPO_ROOT, f)))
      .filter(f => !isPathExcluded(f) && fs.existsSync(path.join(REPO_ROOT, f)) && fs.statSync(path.join(REPO_ROOT, f)).isFile());
  }

  try {
    let cmd = 'git ls-files';
    if (args[0] === '--staged') {
      cmd = 'git diff --cached --name-only --diff-filter=ACMR';
    }
    const output = execSync(cmd, { cwd: REPO_ROOT, encoding: 'utf8' });
    return output
      .split('\n')
      .map(line => line.trim())
      .filter(line => line.length > 0 && !isPathExcluded(line) && fs.existsSync(path.join(REPO_ROOT, line)));
  } catch (err) {
    console.error('Warning: Git command failed, falling back to all markdown and source files.');
    return [];
  }
}

function checkFile(relPath) {
  const fullPath = path.join(REPO_ROOT, relPath);
  let content;
  try {
    content = fs.readFileSync(fullPath, 'utf8');
  } catch (err) {
    return [];
  }
  return checkContent(relPath, content);
}

// Inline suppression: glossary-ignore on the line itself or the line above.
function isIgnored(lines, i) {
  return lines[i].includes('glossary-ignore') || (i > 0 && lines[i - 1].includes('glossary-ignore'));
}

function checkContent(relPath, content) {
  const lines = content.split('\n');
  const violations = [];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (isIgnored(lines, i)) continue;

    for (const rule of VOCABULARY_RULES) {
      const match = rule.pattern.exec(line);
      if (match) {
        violations.push({
          file: relPath,
          line: i + 1,
          column: match.index + 1,
          match: match[0],
          prohibited: rule.prohibited,
          preferred: rule.preferred,
          section: rule.section,
          lineContent: line.trim()
        });
      }
    }
  }

  if (BOLD_REQUIRED_FILES.has(relPath.replace(/\\/g, '/'))) {
    for (const v of findUnboldedTerms(content, loadGlossaryTerms())) {
      violations.push({ file: relPath, ...v });
    }
  }

  return violations;
}

// Glossary terms are the bold definition headings in GLOSSARY.md: a "**Term**:"
// line followed by its definition and an _Avoid_: line.
function loadGlossaryTerms() {
  const glossary = fs.readFileSync(path.join(REPO_ROOT, 'GLOSSARY.md'), 'utf8');
  return [...glossary.matchAll(/^\*\*(.+?)\*\*:\n.*\n_Avoid_:/gm)].map(m => m[1]);
}

function escapeRegExp(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// Reports capitalised glossary terms (or plurals) that appear unbolded in prose.
// Exempt: fenced code, headings, table header rows, inline code, inline link
// text, text already in **bold**, and glossary-ignore lines (see isIgnored).
// Known limits: "Cohort-level" needs **Cohort**-level; a capitalised term
// starting a sentence ("Reveal the ...") is flagged, so use glossary-ignore;
// bare URLs, reference links, indented code and pipe-less tables aren't exempt.
function findUnboldedTerms(content, terms) {
  const lines = content.split('\n');
  const patterns = terms.map(term => ({
    term,
    pattern: new RegExp(`\\b${escapeRegExp(term)}s?\\b`, 'g')
  }));
  const violations = [];
  let inFence = false;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (/^\s*(```|~~~)/.test(line)) {
      inFence = !inFence;
      continue;
    }
    if (inFence || /^\s*#/.test(line) || isIgnored(lines, i)) continue;
    const next = lines[i + 1] || '';
    if (/^\s*\|/.test(line) && /^\s*\|\s*:?-{3}/.test(next)) continue;

    // Blank out exempt spans so reported columns still match the original line.
    const blank = s => ' '.repeat(s.length);
    const prose = line
      .replace(/`[^`]*`/g, blank)
      .replace(/\*\*.+?\*\*/g, blank)
      .replace(/\[[^\]]*\]\([^)]*\)/g, blank);

    for (const { term, pattern } of patterns) {
      for (const match of prose.matchAll(pattern)) {
        violations.push({
          line: i + 1,
          column: match.index + 1,
          match: match[0],
          prohibited: `unbolded ${term}`,
          preferred: `**${match[0]}**`,
          section: term,
          lineContent: line.trim()
        });
      }
    }
  }

  return violations;
}

function main() {
  const args = process.argv.slice(2);
  const files = getFilesToCheck(args);

  if (files.length === 0) {
    console.log('check-glossary: No files to check.');
    process.exit(0);
  }

  let totalViolations = 0;
  const violatingFiles = new Set();

  for (const file of files) {
    const violations = checkFile(file);
    if (violations.length > 0) {
      violatingFiles.add(file);
      totalViolations += violations.length;
      for (const v of violations) {
        console.error(
          `\x1b[31mGLOSSARY VIOLATION\x1b[0m in ${v.file}:${v.line}:${v.column}\n` +
          `  Found: "\x1b[33m${v.match}\x1b[0m" (avoid: ${v.prohibited})\n` +
          `  Use preferred term: \x1b[32m"${v.preferred}"\x1b[0m (GLOSSARY.md: ${v.section})\n` +
          `  Line: > ${v.lineContent}\n`
        );
      }
    }
  }

  if (totalViolations > 0) {
    console.error(
      `\x1b[31mFound ${totalViolations} vocabulary violation${totalViolations === 1 ? '' : 's'} across ${violatingFiles.size} file${violatingFiles.size === 1 ? '' : 's'}.\x1b[0m\n` +
      `Please align with GLOSSARY.md vocabulary before committing or submitting PRs.\n` +
      `If a term is genuinely required, add '<!-- glossary-ignore -->' or '// glossary-ignore' on that line.\n`
    );
    process.exit(1);
  }

  console.log(`✓ Glossary check passed: ${files.length} file(s) comply with GLOSSARY.md vocabulary.`);
  process.exit(0);
}

if (require.main === module) {
  main();
}

module.exports = { checkContent, findUnboldedTerms, loadGlossaryTerms };
