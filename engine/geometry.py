DIRECTIONS = {
    "NORTH": (0, -1),
    "SOUTH": (0, 1),
    "EAST": (1, 0),
    "WEST": (-1, 0),
    "NORTHEAST": (1, -1),
    "NORTHWEST": (-1, -1),
    "SOUTHEAST": (1, 1),
    "SOUTHWEST": (-1, 1),
}

def _sign(value):
    return (value > 0) - (value < 0)

def diagonal_squeeze(walls, x, y, dx, dy):
    if dx == 0 or dy == 0:
        return False
    return (x + dx, y) in walls and (x, y + dy) in walls

def step_open(walls, width, height, x, y, dx, dy):
    nx, ny = x + dx, y + dy
    if not (0 <= nx < width and 0 <= ny < height):
        return False
    if (nx, ny) in walls:
        return False
    return not diagonal_squeeze(walls, x, y, dx, dy)

def line_clear(walls, ax, ay, bx, by):
    if (ax, ay) == (bx, by):
        return True
    dx, dy = abs(bx - ax), abs(by - ay)
    sx, sy = _sign(bx - ax), _sign(by - ay)
    x, y = ax, ay
    ix = iy = 0
    while ix < dx or iy < dy:
        decision = (1 + 2 * ix) * dy - (1 + 2 * iy) * dx
        if decision == 0:
            if (x + sx, y) in walls and (x, y + sy) in walls:
                return False
            x += sx
            y += sy
            ix += 1
            iy += 1
        elif decision < 0:
            x += sx
            ix += 1
        else:
            y += sy
            iy += 1
        if (x, y) != (bx, by) and (x, y) in walls:
            return False
    return True

def shot_path(walls, width, height, x, y, direction, max_range):
    dx, dy = DIRECTIONS[direction]
    cells = []
    for _ in range(max_range):
        if not step_open(walls, width, height, x, y, dx, dy):
            break
        x, y = x + dx, y + dy
        cells.append((x, y))
    return cells

def rotate_cell(x, y, size, times=1):
    for _ in range(times % 4):
        x, y = size - 1 - y, x
    return x, y
