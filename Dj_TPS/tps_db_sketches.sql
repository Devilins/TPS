select s.name from tph_system_consumablesstore c
inner join tph_system_store s on c.store_id = s.id
group by s.name order by s.name;

select c.consumable, c."count", c.change_data, s."name" from tph_system_consumablesstore c
inner join tph_system_store s on c.store_id = s.id
where s."name" = 'Big Wall Airsport Vegas'
order by c.consumable;