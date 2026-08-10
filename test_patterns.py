"""Quick smoke test for all 8 patterns against real transcripts."""
from patterns import PatternRegistry
from patterns.engine import classify
from patterns.weight import weight_pattern
from patterns.lifting import lifting_pattern
from patterns.piano_cardio import piano_pattern, cardio_pattern
from patterns.expense_food import expense_pattern, food_pattern
from patterns.task_correction import task_pattern, correction_pattern
from formatter.schema import validate_item

r = PatternRegistry()
r.register_all([
    weight_pattern, lifting_pattern, piano_pattern, cardio_pattern,
    expense_pattern, food_pattern, task_pattern, correction_pattern,
])

transcripts = {
    'bike_30min': 'Hoje fiz 30 minutos de bicicleta.',
    'supino_3x10x15': 'Fiz três séries de 10 de 15 quilos de supino reto.',
    'supino_variant': 'Fiz 3 séries de 10 de supino reto, 15 quilos.',
    'baiao_de_2': 'Hoje eu comi um baião de 2.',
    'saia_renner': 'Comprei uma saia vermelha da Renner por 80 reais e 30 centavos.',
    'radio_fenac': 'Comprei um rádio relógio de 30 reais e cinquenta centavos, na FENAC.',
    'task_pai': 'Registre tarefa de ir no meu pai no dia dos pais neste domingo.',
    'task_fralda': 'Registre Já de Frauda da Sofia, dia 30 de agosto, às 15h.',
    'balas_canela': 'Comi três balas de canela.',
    'corrige_fralda': 'Corrija comprar fralda da Sofia para chá de fralda da Sofia.',
    'jogo_sp': 'Hoje eu assisti o jogo do São Paulo contra Santos, foi 3x1.',
    'cafe': 'Tomei uma caneca de café.',
    'condominio': 'Paguei condomínio.',
    'pamela': 'Paguei Pâmela Sensei',
}

stats = {'matched': 0, 'unmatched': 0}
for name, text in transcripts.items():
    items_raw, unmatched = classify(text, r)
    items = [validate_item(i) for i in items_raw]

    if items:
        stats['matched'] += 1
        for item in items:
            src = item.source
            detail = ''
            d = item.data
            if hasattr(d, 'activity'):
                detail = ' activity=' + str(d.activity)
            elif hasattr(d, 'description'):
                detail = ' "' + str(d.description)[:60] + '"'
            elif hasattr(d, 'text'):
                detail = ' "' + str(d.text)[:60] + '"'
            elif hasattr(d, 'exercise_hint'):
                detail = ' "' + str(d.exercise_hint)[:40] + '"'
                if hasattr(d, 'sets') and d.sets:
                    detail += ' ' + str(d.sets) + 'sets'
                if hasattr(d, 'reps') and d.reps:
                    detail += ' ' + str(d.reps) + 'reps'
                if hasattr(d, 'weight_kg') and d.weight_kg:
                    detail += ' @' + str(d.weight_kg) + 'kg'
            elif hasattr(d, 'weight_kg'):
                detail = ' ' + str(d.weight_kg) + 'kg'
            elif hasattr(d, 'amount'):
                detail = ' R$' + str(d.amount)
                if hasattr(d, 'description'):
                    detail += ' "' + str(d.description)[:40] + '"'
            elif hasattr(d, 'task_hint'):
                detail = ' "' + str(d.task_hint) + '"'
            elif hasattr(d, 'search_hint'):
                detail = ' "' + str(d.search_hint) + '" -> ' + str(d.new_value)

            label = '  OK  ' + name.ljust(20) + ' ' + src.ljust(25)
            label += ' -> ' + item.type.ljust(12)
            if item.habit:
                label += '/' + item.habit
            label += detail
            print(label)
    else:
        stats['unmatched'] += 1
        print('  ??  ' + name.ljust(20) + ' UNMATCHED -> LLM fallback')

print()
print('Pattern match rate: ' + str(stats['matched']) + '/' +
      str(len(transcripts)) + ' = ' +
      str(round(100 * stats['matched'] / len(transcripts))) + '%')
