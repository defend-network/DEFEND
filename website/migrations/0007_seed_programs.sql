INSERT OR IGNORE INTO programs (
  id, slug, title, summary, description, chapter_id, status, capacity,
  fee_cents, eligibility, family_friendly, youth_safeguarding_required
) VALUES
(
  'program_trades', 'trades-and-entrepreneurship', 'Trades & Entrepreneurship',
  'Practical support for members building skills, trades, and small businesses.',
  'DEFEND is developing a member network for trades education, professional development, referrals, and entrepreneurship. The network is intended to help members build useful relationships and share practical knowledge.',
  'chapter_pasco', 'in_development', NULL, 0, 'Open to members and prospective members as programs open.', 0, 0
),
(
  'program_mentorship', 'mentorship', 'Mentorship',
  'Connecting experienced members with people entering a trade or profession.',
  'A mentorship program is being designed to pair experienced members with participants who want guidance in a trade, profession, or business. Participation will be voluntary and subject to program rules.',
  'chapter_pasco', 'planned', NULL, 0, 'Adults; program rules apply.', 0, 0
),
(
  'program_fitness', 'fitness-and-boxing', 'Fitness & Boxing',
  'Physical fitness, discipline, and athletic development through structured activity.',
  'DEFEND intends to support fitness and boxing activities as part of its commitment to personal responsibility and physical development. Any youth-focused activity will require approved safeguarding, consent, and supervision policies before it is enabled.',
  'chapter_pasco', 'planned', NULL, 0, 'Adults; youth participation disabled pending safeguarding approval.', 0, 0
),
(
  'program_cultural', 'cultural-education', 'Cultural Education',
  'Heritage, history, and cultural learning for members and their families.',
  'DEFEND is developing educational and cultural activities that explore European heritage and its place in American community life. Public resources will be clearly separated from member-only materials.',
  'chapter_pasco', 'in_development', NULL, 0, 'Members and families.', 1, 0
),
(
  'program_service', 'community-service', 'Community Service',
  'Volunteer service and local projects that strengthen the community.',
  'DEFEND is developing volunteer and community-service opportunities in Pasco County. Service projects will be announced only when they are confirmed and ready for participants.',
  'chapter_pasco', 'planned', NULL, 0, 'Volunteers; specific project requirements apply.', 1, 0
),
(
  'program_mens', 'mens-mentorship-and-fitness', 'Men''s Mentorship & Fitness',
  'Lawful mentorship, fitness, and personal-development programming for men.',
  'DEFEND is developing men''s mentorship and fitness activities focused on responsibility, discipline, trades, and professional development. Participation is voluntary and subject to program rules and lawful eligibility requirements.',
  'chapter_pasco', 'planned', NULL, 0, 'Adults; lawful eligibility and program rules apply.', 0, 0
),
(
  'program_family', 'womens-and-family-workshops', 'Women''s & Family Workshops',
  'Workshops and community programming for women, families, and household participation.',
  'DEFEND is developing women''s and family workshops covering practical skills, cultural education, entrepreneurship, and community participation. Family participation is optional and does not change the standard membership tier.',
  'chapter_pasco', 'planned', NULL, 0, 'Women and families; specific workshop rules apply.', 1, 0
);
