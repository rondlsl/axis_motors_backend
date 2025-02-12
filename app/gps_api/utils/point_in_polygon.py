def is_point_inside_polygon(lat: float, lon: float, polygon_coords: list) -> bool:
    """
    Проверяет, находится ли точка внутри многоугольника (метод Ray-Casting).

    :param lat: Широта точки
    :param lon: Долгота точки
    :param polygon_coords: Список координат [(lon1, lat1), (lon2, lat2), ...] многоугольника
    :return: True, если точка внутри, иначе False
    """
    num_vertices = len(polygon_coords)
    inside = False

    x, y = lon, lat  # Долгота — X, широта — Y
    j = num_vertices - 1  # Последний индекс в списке

    for i in range(num_vertices):
        xi, yi = polygon_coords[i]
        xj, yj = polygon_coords[j]

        # Проверяем, пересекает ли луч от точки сторону многоугольника
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside  # Инвертируем флаг

        j = i  # Смещаем предыдущее значение

    return inside
