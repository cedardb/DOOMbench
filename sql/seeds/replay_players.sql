-- Replay scene: corridor assault
-- P1 starts in Room A (west) and advances east while firing.
-- P2 starts in Room B (east) and charges west toward P1.
-- P2 spawns deep in Room B after each death -- visible teleport shows the kill landed.
INSERT INTO mobs(kind, x, y, dir, name, sprite_id, minimap_icon) VALUES
  ('player',  7.0,  6.5,  0.0,     'Player1', 0, '1'),
  ('player', 22.0,  6.5,  3.14159, 'Player2', 0, '2');

INSERT INTO players(id, spawn_x, spawn_y, spawn_dir) VALUES
  (1,  7.0,  6.5,  0.0),
  (2, 30.0,  6.5,  3.14159);
