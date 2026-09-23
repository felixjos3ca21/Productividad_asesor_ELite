SELECT Count(*) from pagos_x_asesor;

SELECT count(*) - count(distinct cuenta || '|' || valor_pago || '|' || fecha_pago) as Posibles_duplicado from pagos_x_asesor;

DELETE from pagos_x_asesor
Where clave_pago NOT IN (
	SELECT MAX(clave_pago)
	FROM pagos_x_asesor
	GROUP BY cuenta , valor_pago, fecha_pago);