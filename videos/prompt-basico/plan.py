import json
T=json.load(open('tr.json'))
seg={int(k):(v['a'],v['b']) for k,v in T.items()}
# texto corrigido (None = sem legenda). trim: fim alternativo p/ o segmento
keep={
0:"Você já recebeu um trabalho de estagiário",1:"completamente fora do que você pediu?",
3:"Com a IA é exatamente a mesma coisa.",
6:"Quando você faz um bom prompt, ele precisa de certos elementos, como...",
7:"o papel, o contexto, a tarefa e o formato.",
8:"Qual vai ser o papel da IA",9:"nesse contexto?",10:"Quem a IA deve ser naquele momento.",
11:"Isso nem sempre é necessário.",12:"Algumas vezes elas conseguem entender isso automaticamente.",
13:"O contexto: o que ela não sabe, o que ela precisa saber.",
14:None,15:"...consegue ler coisas no seu computador.",
16:"Talvez ela consiga procurar esse contexto pra ti.",
18:"Na maioria dos casos, ela precisa saber disso.",
20:"você dar essa documentação, esse contexto a mais,",21:"é extremamente fundamental.",
22:"E existem formas para você fazer isso, que a gente vai ver em outros vídeos.",
29:"E a tarefa, sem ambiguidade. O que você quer que ela faça?",
30:"Ela já sabe o papel dela, ela já sabe o contexto. Agora, o que ela tem que fazer",
31:"para entregar aquilo que você precisa.",
33:"Qual vai ser o formato da tua resposta? Aí ela precisa fazer um slide, um PDF. Ela precisa que você...",
34:"retorne uma tabela.",35:"Existem muitas coisas que precisam ser consideradas.",
37:"Estou com um contrato, peço para resumir.",
49:"Para um prompt vago, “resume esse contrato”.",
50:"Pode ser que os resultados desse prompt vago sejam bons, mas você não sabe.",
51:"Qual vai ser o resultado?",
52:"Se você vai ter no seu formato certo, se ele vai ter o contexto certo e se ele vai estar atuando da forma como você gostaria.",
53:"Agora, se a gente for estruturar de uma forma um pouco mais...",54:None,
55:"Você é um advogado especialista em contratos",56:"empresariais.",
57:"Vou te enviar um contrato de prestação de serviços.",58:"Meu cliente é o contratante.",
59:"Quero um resumo executivo com:",60:"1. Objeto do contrato; obrigações",
61:"principais de cada parte; cláusulas de rescisão; pontos de atenção ou riscos para o contratante.",
62:"Use linguagem direta, sem jargão técnico: esse resumo vai para o cliente, não para mim.",
63:"Então você tem o papel, o contexto, a tarefa e o formato aqui.",
64:"Algumas dessas informações",65:"podem ser inferidas.",
68:"Por exemplo,",69:"que o documento enviado é um contrato de prestação de serviços",
70:"e que você é o contratante.",71:"o cliente ou o contratante",72:"e você é o contratado.",
73:"Agora, a parte da tarefa é a mais importante,",74:"porque você está detalhando as coisas que você precisa.",
76:"E como isso vai ser usado: o formato.",
77:"Então, quando você fala que o resumo vai para o cliente, não para mim,",
79:"tá falando pra IA algumas coisas",80:"que precisam ser mais claras, ou",81:"talvez que algumas coisas precisam ser omitidas.",
83:"Não é mais difícil de escrever.",
84:"É apenas mais pensado. E conforme passa o tempo e você faz alguns desses, vai ficar extremamente natural.",
86:"Escreva dois prompts para a mesma tarefa e você vai ver as diferenças do resultado.",
87:"O mais simples possível, como “resuma algo”.",
88:"Você pode fazer isso mais de uma vez, você vai ver que os resultados vão ser diferentes. Claro, o resultado do segundo também vai ser diferente, mas muito mais conciso e seguindo a mesma lógica.",
}
trim_end={22:79.1}
idx=sorted(keep)
items=[]
for i in idx:
    a,b=seg[i]; b=trim_end.get(i,b)
    items.append(dict(i=i,a=a,b=b,t=keep[i]))
# agrupar
groups=[]; 
for n,it in enumerate(items):
    if groups:
        g=groups[-1]; p=g[-1]
        gap=it['a']-p['b']
        if it['i']==p['i']+1 and gap<1.2:
            g.append(it); continue
    groups.append([it])
LEAD,TAIL=0.15,0.22
plan=[]
for g in groups:
    s=max(0,g[0]['a']-LEAD); e=g[-1]['b']+TAIL
    # nao invadir segmento cortado vizinho demais: ok
    ev=[]
    for it in g:
        if not it['t']: continue
        ev.append((it['a']-s,it['b']-s,it['t']))
    plan.append(dict(s=round(s,3),e=round(e,3),ev=ev))
json.dump(plan,open('plan.json','w'),ensure_ascii=False,indent=1)
tot=sum(p['e']-p['s'] for p in plan)
print(len(plan),'clipes; duracao final %.1fs (original 356s)'%tot)
