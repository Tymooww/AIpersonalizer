db = db.getSiblingDB('personalizedpages');

db.createUser({
  user: 'AIpersonalizerAuth',
  pwd: 'yL3JNz%LUvVEtx',
  roles: [
    {
      role: 'readWrite',
      db: 'personalizedpages'
    }
  ]
});

db.createCollection('pages');