#!/usr/bin/env node

import { createHash } from 'node:crypto';
import {
  access,
  mkdir,
  readdir,
  readFile,
  rm,
  writeFile,
} from 'node:fs/promises';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(__dirname, '..', '..');
const sourceRoot = join(repoRoot, 'src', 'ui-ux-pro-max');
const assetRoot = join(repoRoot, 'cli', 'assets');
const dirsToSync = ['data', 'scripts', 'templates'];
const checkOnly = process.argv.includes('--check');

// The 6 sibling sub-skills are bundled (as static copies) so `uipro init`
// installs all 7 skills, not just the template-rendered orchestrator. Source
// of truth is .claude/skills/ (the orchestrator ui-ux-pro-max is rendered from
// templates at install time, so it is not mirrored here).
const skillsSourceRoot = join(repoRoot, '.claude', 'skills');
const skillsAssetRoot = join(assetRoot, 'skills');
const subSkills = ['banner-design', 'brand', 'design', 'design-system', 'slides', 'ui-styling'];

// ponytail: only text is bundled. Excludes (a) heavy binary assets — the
// canvas fonts are ~5.8MB and a skill registers from its SKILL.md, not its
// fonts — and (b) Python build cruft (__pycache__/*.pyc, .coverage) that would
// otherwise be picked up from a local run.
const isExcludedAssetFile = (rel) =>
  rel.split('/').some((seg) => seg === 'canvas-fonts' || seg === '__pycache__') ||
  /\.(ttf|otf|woff2?|png|jpe?g|gif|ico|coverage|pyc)$/i.test(rel);

// ponytail: all synced assets are text (csv/json/md/py); normalize CRLF->LF so
// the byte hash and the on-disk copy don't drift with git autocrlf across platforms.
const toLF = (text) => text.replace(/\r\n/g, '\n');

async function exists(path) {
  try {
    await access(path);
    return true;
  } catch {
    return false;
  }
}

function assertInsideRepo(path) {
  const resolvedPath = resolve(path);
  if (!resolvedPath.startsWith(repoRoot)) {
    throw new Error(`Refusing to modify path outside repository: ${resolvedPath}`);
  }
  return resolvedPath;
}

async function listFiles(root) {
  const files = [];

  async function walk(dir) {
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      const fullPath = join(dir, entry.name);
      if (entry.isDirectory()) {
        await walk(fullPath);
      } else if (entry.isFile()) {
        files.push(relative(root, fullPath).replaceAll('\\', '/'));
      }
    }
  }

  await walk(root);
  return files.sort();
}

async function fileHash(path) {
  const content = toLF(await readFile(path, 'utf8'));
  return createHash('sha256').update(content).digest('hex');
}

async function checkAssets() {
  const drift = [];

  for (const dir of dirsToSync) {
    const sourceDir = join(sourceRoot, dir);
    const targetDir = join(assetRoot, dir);

    if (!(await exists(sourceDir))) {
      drift.push(`missing source directory: ${relative(repoRoot, sourceDir)}`);
      continue;
    }
    if (!(await exists(targetDir))) {
      drift.push(`missing asset directory: ${relative(repoRoot, targetDir)}`);
      continue;
    }

    const sourceFiles = (await listFiles(sourceDir)).filter((f) => !isExcludedAssetFile(f));
    const targetFiles = (await listFiles(targetDir)).filter((f) => !isExcludedAssetFile(f));
    const allFiles = [...new Set([...sourceFiles, ...targetFiles])].sort();

    for (const file of allFiles) {
      const sourcePath = join(sourceDir, file);
      const targetPath = join(targetDir, file);

      if (!sourceFiles.includes(file)) {
        drift.push(`extra asset file: ${dir}/${file}`);
      } else if (!targetFiles.includes(file)) {
        drift.push(`missing asset file: ${dir}/${file}`);
      } else if ((await fileHash(sourcePath)) !== (await fileHash(targetPath))) {
        drift.push(`stale asset file: ${dir}/${file}`);
      }
    }
  }

  // Sub-skills (text content only; fonts/binaries intentionally excluded)
  for (const name of subSkills) {
    const sourceDir = join(skillsSourceRoot, name);
    const targetDir = join(skillsAssetRoot, name);

    if (!(await exists(sourceDir))) {
      drift.push(`missing source sub-skill: ${relative(repoRoot, sourceDir)}`);
      continue;
    }
    if (!(await exists(targetDir))) {
      drift.push(`missing asset sub-skill: skills/${name}`);
      continue;
    }

    const sourceFiles = (await listFiles(sourceDir)).filter((f) => !isExcludedAssetFile(f));
    const targetFiles = (await listFiles(targetDir)).filter((f) => !isExcludedAssetFile(f));
    const allFiles = [...new Set([...sourceFiles, ...targetFiles])].sort();

    for (const file of allFiles) {
      const sourcePath = join(sourceDir, file);
      const targetPath = join(targetDir, file);

      if (!sourceFiles.includes(file)) {
        drift.push(`extra asset file: skills/${name}/${file}`);
      } else if (!targetFiles.includes(file)) {
        drift.push(`missing asset file: skills/${name}/${file}`);
      } else if ((await fileHash(sourcePath)) !== (await fileHash(targetPath))) {
        drift.push(`stale asset file: skills/${name}/${file}`);
      }
    }
  }

  if (drift.length > 0) {
    console.error('CLI assets are out of sync with src/ui-ux-pro-max:');
    for (const item of drift) {
      console.error(`  - ${item}`);
    }
    console.error('\nRun: npm run sync:assets');
    process.exit(1);
  }

  console.log('CLI assets are in sync.');
}

async function syncAssets() {
  assertInsideRepo(assetRoot);
  await mkdir(assetRoot, { recursive: true });

  for (const dir of dirsToSync) {
    const sourceDir = join(sourceRoot, dir);
    const targetDir = assertInsideRepo(join(assetRoot, dir));

    if (!(await exists(sourceDir))) {
      throw new Error(`Source directory does not exist: ${sourceDir}`);
    }

    if (await exists(targetDir)) {
      await rm(targetDir, { recursive: true, force: true });
    }

    for (const file of await listFiles(sourceDir)) {
      if (isExcludedAssetFile(file)) continue;
      const targetPath = assertInsideRepo(join(targetDir, file));
      await mkdir(dirname(targetPath), { recursive: true });
      await writeFile(targetPath, toLF(await readFile(join(sourceDir, file), 'utf8')));
    }
  }

  // Sub-skills: copy text content only (fonts/binaries excluded) so all 7
  // skills ship in the package without bloating it with ~5.8MB of fonts.
  const skillsTarget = assertInsideRepo(skillsAssetRoot);
  if (await exists(skillsTarget)) {
    await rm(skillsTarget, { recursive: true, force: true });
  }
  for (const name of subSkills) {
    const sourceDir = join(skillsSourceRoot, name);
    if (!(await exists(sourceDir))) {
      throw new Error(`Source sub-skill does not exist: ${sourceDir}`);
    }
    for (const file of await listFiles(sourceDir)) {
      if (isExcludedAssetFile(file)) continue;
      const targetPath = assertInsideRepo(join(skillsTarget, name, file));
      await mkdir(dirname(targetPath), { recursive: true });
      await writeFile(targetPath, toLF(await readFile(join(sourceDir, file), 'utf8')));
    }
  }

  console.log('Synced CLI assets from src/ui-ux-pro-max + 6 sub-skills (normalized to LF).');
}

if (checkOnly) {
  await checkAssets();
} else {
  await syncAssets();
}
