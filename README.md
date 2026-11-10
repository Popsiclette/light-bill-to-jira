# light-bill-to-jira

Cria todo mês a tarefa de reembolso no Jira com a conta do mês anterior anexada, já sem a senha do PDF. Roda no GitHub Actions todos os dias, do dia 1 ao dia 10, às 09:00 (horário de Brasília), e não faz nada se a tarefa do mês já existir.

## O que é necessário

1. Arquivo a ser anexado no ticket chegando em um e-mail Gmail
2. Filtro que capture o e-mail e adicione a tag `reembolso`
3. Projeto no Google Cloud
4. Python instalado no computador
5. Token de API do Jira
6. Conta GitHub

## Adicionando a tag nos e-mails com o PDF

1. Na barra de pesquisa do Gmail, digite uma busca que traga apenas os e-mails com a conta em anexo e pressione Enter. Por exemplo: `from:<remetente> has:attachment`
2. Confira os resultados. Se aparecer algum e-mail que não é da conta, refine a busca (por exemplo, com `filename:pdf` ou `subject:fatura`)
3. Clique no botão **Mostrar opções de pesquisa**, à direita da barra de pesquisa. O formulário abre preenchido com a busca
4. Clique em **Criar filtro**
5. Na tela seguinte, marque **Aplicar o marcador** → **Novo marcador** → `reembolso`, e também **Aplicar filtro às conversas correspondentes**
6. Clique em **Criar filtro**

O valor e a data de vencimento são lidos do texto do e-mail usando regexes `AMOUNT_PATTERN` e `DUE_DATE_PATTERN` (para captar `R$ …` e `vencimento dd/mm/aaaa`, respectivamente) em `reimburse.py`. Ajuste conforme formatação do seu e-mail.

## Criando URLs públicas

Siga os passos abaixo logado na sua conta Github.

1. Acesse [gist.github.com](https://gist.github.com)
2. Crie um gist com:
   - **Filename:** `privacy-policy.md`
   - **Conteúdo:** por exemplo, `App de uso pessoal. Lê somente o Gmail do próprio dono, em modo somente leitura, para buscar contas a reembolsar. Nenhum dado é compartilhado com terceiros.`
3. Clique em **Create public gist**

## Criando o projeto no Google Cloud

Faça tudo logado na conta Google que recebe o e-mail com o PDF. Os nomes abaixo seguem a interface do console em inglês.

1. Em [console.cloud.google.com](https://console.cloud.google.com), no seletor de projetos no topo, clique em **New project**, dê um nome (por exemplo, `bill-to-jira`) e clique em **Create**. Confira que o projeto novo ficou selecionado.
2. Em **APIs & Services → Library**, procure **Gmail API** e clique em **Enable**.
3. Em **Google Auth Platform**, clique em **Get started**, preencha o nome do app e seu e-mail como e-mail de suporte, escolha **External** em **Audience** e conclua.
4. Em **Data Access → Add or remove scopes**, selecione `.../auth/gmail.readonly` e salve.
5. Em **Branding**, preencha **App homepage** e **Privacy policy link** com a URL do gist criado na etapa anterior. Não envie logo: com logo, o Google passa a exigir a verificação do app e ele não pode ficar em produção sem ela.
6. Adicione `github.com` em **Authorized domains**.
7. Em **Audience**, clique em **Publish app** e confirme. O status deve ficar **In production**; sem isso, o refresh token expira a cada 7 dias. O aviso de que o app precisa de verificação pode ser ignorado, então não clique em **Go to verification center**.
8. Em **Clients → Create client**, escolha **Desktop app**, crie o cliente e clique em **Download JSON**.
9. Renomeie o arquivo para `client_secret.json`: ele é usado na próxima seção, e o `client_id` e o `client_secret` dele vão nos secrets `GMAIL_CLIENT_ID` e `GMAIL_CLIENT_SECRET`.

## Criando a automação

Faça um fork desse repositório no seu GitHub. 

### Secrets

Nas configurações do repositório, vá em **Secrets and variables → Actions** e crie os secrets abaixo.

#### `GMAIL_CLIENT_ID` e `GMAIL_CLIENT_SECRET`

Encontre os valores no arquivo `client_secret.json`.

#### `GMAIL_REFRESH_TOKEN`

Tenha o `get_refresh_token.py` na mesma pasta em que está o `client_secret.json`. De dentro dela, execute:

```powershell
py -m pip install google-auth-oauthlib; py get_refresh_token.py
```

A página de login do Google será aberta no navegador e pedirá acesso de somente leitura ao seu Gmail. Como o app não é verificado, o Google mostra o aviso "Google hasn't verified this app": clique em **Advanced** → **Go to <nome do app> (unsafe)** e continue. Um refresh token será impresso no terminal.

Guarde o token impresso no secret `GMAIL_REFRESH_TOKEN` e apague o `client_secret.json` em seguida.

#### `JIRA_API_TOKEN`

1. Acesse [id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens), logado na sua conta Atlassian da Akross.
2. Clique em **Create API token with scopes**.
3. Dê um nome ao token e escolha a data de expiração (o máximo é 1 ano). Anote a data: quando o token expirar, a automação para de funcionar até você criar um novo e atualizar o secret.
4. Em **App**, escolha **Jira**.
5. Selecione os escopos `read:jira-work`, `write:jira-work` e `read:jira-user`.
6. Clique em **Create** e copie o token direto para o secret `JIRA_API_TOKEN`. **Ele não é exibido de novo**.

#### `JIRA_EMAIL`

Seu e-mail usado no Jira.

#### `PDF_PASSWORD`

Senha do PDF, caso haja.

#### `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID` (opcionais)

Com esses dois secrets, você recebe uma mensagem no Telegram quando a tarefa é criada ou quando a execução falha. Cada pessoa cria o próprio bot: não compartilhe o token, porque quem o tem consegue enviar mensagens como o bot e ler o que é enviado a ele.

1. No Telegram, abra o **@BotFather** (confira o selo azul de verificado) e envie `/newbot`.
2. Escolha um nome de exibição e um username terminado em `bot`. O BotFather responde com o token: salve-o direto no secret `TELEGRAM_BOT_TOKEN`.
3. Abra o chat com o seu bot pelo link que o BotFather enviou, clique em **Start** e mande qualquer mensagem.
4. No navegador, abra `https://api.telegram.org/bot<TOKEN>/getUpdates`, trocando `<TOKEN>` pelo token. Procure `"chat":{"id":` e salve o número no secret `TELEGRAM_CHAT_ID`. Se o resultado vier vazio, mande outra mensagem ao bot e recarregue a página.
5. Apague essa página do histórico do navegador, porque o token fica na URL.

### Variáveis

#### `TICKET_NAME`

O resumo é `Auxílio Home Office - <nome>`, e o nome vem do seu perfil no Jira. Para usar outra grafia (por exemplo, com acentos), crie esta variável em **Settings → Secrets and variables → Actions → Variables**.

### Actions

1. No seu fork, abra a aba **Actions** e clique em **I understand my workflows, go ahead and enable them**. O GitHub deixa os workflows desligados em forks, e sem isso nada roda, sem nenhum aviso de erro.
2. Para testar, selecione o workflow **Auxílio Home Office** e clique em **Run workflow**. Se a tarefa do mês ainda não existir, ela é criada; se já existir, o log mostra a chave dela e nada é feito.
3. A partir daí, o workflow roda sozinho todos os dias, do dia 1 ao dia 10, às 09:00 (horário de Brasília).
4. Com o Telegram configurado, você recebe uma mensagem quando a tarefa é criada e quando a execução falha. Sem ele, o único aviso é o e-mail que o próprio GitHub envia em caso de falha: deixe essa notificação ligada em **Settings → Notifications → Actions** (configurações da sua conta GitHub, não do repositório).
