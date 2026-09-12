# Component sources

## Ambient particles

The page backdrop adapts the circle rendering, edge fade, and gentle pointer displacement from [Magic UI Particles](https://magicui.design/docs/components/particles).

- [Pinned upstream source](https://github.com/magicuidesign/magicui/blob/ec1cce6c4192c0aaac279dd7e53537ccd5c99d44/apps/www/registry/magicui/particles.tsx)
- [MIT license](../frontend/public/licenses/magic-ui.txt), copyright Magic UI.
- Local implementation: `frontend/src/AmbientBackdrop.tsx`.
- Adaptations: scoped React effect, bounded canvas resolution and particle count, time-based drift at up to 20 frames per second, reduced-motion support, hidden-page/fullscreen suspension, no animation library dependency, and no React updates on pointer movement.

The muted green, amber, and lavender light fields and page composition are project-specific CSS. Ambient motion is decorative and uses its own deterministic seed; it never reads market data, modifies agent randomness, or represents neural firing.
