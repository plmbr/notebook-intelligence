// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

// Pin the JSON wire-format contract for skills. The HTTP layer speaks
// snake_case; the panel/API speaks camelCase. A typo in either direction
// would silently corrupt the most important user-facing state ("I
// toggled tracking on but it didn't stick after reload"), and the Python
// tests can't catch it because they test the response shape they
// produce, not the names the TS layer reads.
//
// Tested via the exported `skillFromWire` decoder. Encoders are validated
// in the panel/API call sites; their snake-case fields are direct
// literals in the request body, easy to read in src/api.ts.

import { skillFromWire } from '../../src/api';

describe('skillFromWire', () => {
  function baseWire(extras: Record<string, unknown> = {}) {
    return {
      scope: 'user',
      name: 'sk',
      description: 'd',
      allowed_tools: ['Read'],
      root_path: '/r',
      files: ['SKILL.md'],
      source: 'https://github.com/owner/repo',
      managed: false,
      managed_source: '',
      managed_ref: '',
      tracks_upstream: false,
      tracking_ref: '',
      body: 'body',
      ...extras
    };
  }

  it('reads tracks_upstream and tracking_ref from wire snake_case', () => {
    const skill = skillFromWire(
      baseWire({ tracks_upstream: true, tracking_ref: 'deadbeef' })
    );
    expect(skill.tracksUpstream).toBe(true);
    expect(skill.trackingRef).toBe('deadbeef');
  });

  it('defaults tracking fields when absent', () => {
    // Older backend that doesn't know about the feature: snake_case keys
    // are missing entirely. Frontend must still produce a well-typed
    // ISkillDetail with falsy tracking fields rather than NaN/undefined.
    const wire: any = { ...baseWire() };
    delete wire.tracks_upstream;
    delete wire.tracking_ref;
    const skill = skillFromWire(wire);
    expect(skill.tracksUpstream).toBe(false);
    expect(skill.trackingRef).toBe('');
  });

  it('coerces non-boolean tracks_upstream to false', () => {
    // The wire field is server-controlled, but the coercion belt-and-
    // suspenders catches the case where a manually-edited SKILL.md
    // surfaces a truthy-string ("true") that pyyaml didn't normalize.
    const skill = skillFromWire(baseWire({ tracks_upstream: 'true' as any }));
    expect(skill.tracksUpstream).toBe(true); // Boolean('true') is true
    const skill2 = skillFromWire(baseWire({ tracks_upstream: 0 as any }));
    expect(skill2.tracksUpstream).toBe(false);
  });

  it('reads managed and tracking fields independently', () => {
    // The two metadata pairs are mutually exclusive in practice but
    // the wire format treats them as independent. Confirm both decode
    // separately so a future refactor that unifies them has a clean
    // failure mode.
    const skill = skillFromWire(
      baseWire({
        managed: true,
        managed_source: 'https://github.com/org/repo',
        managed_ref: 'sha1'
      })
    );
    expect(skill.managed).toBe(true);
    expect(skill.managedSource).toBe('https://github.com/org/repo');
    expect(skill.managedRef).toBe('sha1');
    // Default tracking fields untouched.
    expect(skill.tracksUpstream).toBe(false);
  });
});
