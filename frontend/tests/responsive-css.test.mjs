import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const css = readFileSync(new URL('../src/app/portal.css', import.meta.url), 'utf8');

test('tablet public header hides the desktop portal navigation', () => {
  assert.match(css, /@media\(max-width:900px\)\{[^}]*\.premium-topbar \.portal-nav\{display:none\}/);
});

test('public portal prevents decorative content from causing horizontal page overflow', () => {
  assert.match(css, /\.premium-page\{[^}]*overflow-x:hidden/);
});

test('narrow phone header hides the brand wordmark but keeps the icon', () => {
  assert.match(css, /@media\(max-width:430px\)\{[^}]*\.premium-topbar \.brand strong\{display:none\}/);
});

test('narrow phone showcase uses transforms sized for a 320px viewport', () => {
  assert.match(css, /@media\(max-width:430px\)\{[\s\S]*?\.phone-back\{transform:translateX\(-58px\) rotate\(-8deg\) scale\(\.70\)\}/);
  assert.match(css, /@media\(max-width:430px\)\{[\s\S]*?\.phone-front\{transform:translateX\(55px\) rotate\(6deg\) scale\(\.75\)\}/);
});
