content = open('website/index.html', encoding='utf-8').read()

checks = [
    ('Hero section present',     'id="hero"' in content),
    ('Overview section present', 'id="overview"' in content),
    ('Examples section present', 'id="examples"' in content),
    ('Results section present',  'id="results"' in content),
    ('Tradeoffs section present','id="tradeoffs"' in content),
    ('Downloads section present','id="downloads"' in content),
    ('Footer present',           '<footer>' in content),
    ('Real name: Sarthak',       'Sarthak Malvadkar' in content),
    ('Fake name: Priya Kakar',   'Priya Kakar' in content),
    ('Real email',               'cs.connect@kshinternational.com' in content),
    ('Real CIN',                 'U28129PN1979PLC141032' in content),
    ('Fake CIN',                 'U93952RJ2013PLC340916' in content),
    ('Eval table class',         'eval-table' in content),
    ('Precision 84.1',           '84.1%' in content),
    ('Recall 100',               '100.0%' in content),
    ('FILL IN markers (2)',      content.count('[FILL IN') >= 2),
    ('Inter font loaded',        'Inter' in content),
    ('Dark theme vars',          '--bg:' in content),
    ('JetBrains Mono',           'JetBrains Mono' in content),
    ('Scroll animation JS',      'IntersectionObserver' in content),
]

print('HTML structure checks:')
all_pass = True
for label, result in checks:
    status = 'PASS' if result else 'FAIL'
    if not result:
        all_pass = False
    print(f'  {status}  {label}')

size_kb = round(len(content.encode('utf-8')) / 1024, 1)
print(f'\n  INFO  File size: {size_kb} KB')
print(f'\n  {"ALL CHECKS PASSED" if all_pass else "SOME CHECKS FAILED"}')
