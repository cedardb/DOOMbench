-- Act 1 scene setup:
--   Players 1 & 2 duel in Room A — facing each other, bullet mid-flight between them.
--   Players 3 & 4 face nearby walls (Room D south, Room F east) for strong wall rendering.

INSERT INTO mobs(kind, x, y, dir, name, sprite_id, minimap_icon) VALUES
  ('player',  4.0,  6.0,  0.117,  'Player1', 0, '1'),  -- Room A west, aimed at Player 2 (atan2(1,8.5))
  ('player', 12.5,  7.0,  3.258,  'Player2', 0, '2'),  -- Room A east, aimed back at Player 1 (π+0.117)
  ('player', 12.0, 24.5,  1.5708, 'Player3', 0, '3'),  -- Room D, facing south wall (~4.5 tiles away)
  ('player', 57.5, 22.0,  0.0,    'Player4', 0, '4'),  -- Room F, facing east wall (~3.5 tiles away)
  ('bullet',  8.0,  6.0,  0.0,    'Bullet',  4, '*');  -- Room A, mid-flight east from P1 toward P2

INSERT INTO players(id, spawn_x, spawn_y, spawn_dir) VALUES
  (1,  4.0,  6.0,  0.117),
  (2, 12.5,  7.0,  3.258),
  (3, 12.0, 24.5,  1.5708),
  (4, 57.5, 22.0,  0.0);
