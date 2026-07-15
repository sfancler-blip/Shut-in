INSERT INTO region VALUES ('portland-or', 'Portland, OR', 'America/Los_Angeles');

INSERT INTO theater (id, region_id, name, website_url, timezone, adapter, adapter_config)
VALUES
  ('hollywood-theatre', 'portland-or', 'Hollywood Theatre',
   'https://hollywoodtheatre.org', 'America/Los_Angeles',
   'wordpress_gecko', '{"base_url": "https://hollywoodtheatre.org"}'),
  ('cinemagic', 'portland-or', 'Cinemagic',
   'https://www.thecinemagictheater.com', 'America/Los_Angeles',
   'indy', '{"base_url": "https://tickets.thecinemagictheater.com"}');
