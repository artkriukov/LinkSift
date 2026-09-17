# Git workflow

Используем упрощённый Gitflow: `main` — стабильная версия; `preprod` — интеграция
и проверка совместной работы фич; короткие ветки — отдельные изменения.
`preprod` выполняет роль `develop` и стенда проверки, третья постоянная ветка не нужна.
Наличие ветки само по себе не создаёт стенд: развёртывание настраивается отдельно.

```text
preprod → feature/имя → PR → preprod → release PR → main → tag
main → hotfix/имя → PR → main → sync PR → preprod
```

## Первый коммит текущего каркаса

`main` уже содержит исходное ТЗ. Локальная `preprod` создана от `main`, рабочая
`chore/project-setup` — от `preprod`. Коммиты и push выполняет владелец.

```sh
cd /Users/artemkriukov/Desktop/LinkSift
git status
git branch --show-current
# ожидается chore/project-setup
make check
make test
git add .
git diff --cached --stat
git commit -m "chore: bootstrap LinkSift architecture and development environment"
git push -u origin preprod
git push -u origin chore/project-setup
```

Создать PR **chore/project-setup → preprod**. `main` напрямую не обновлять.
В интерфейсе GitHub обязательно выбрать base `preprod` (default branch будет `main`).

## Новая фича

```sh
git switch preprod
git pull --ff-only origin preprod
git switch -c feature/telegram-upload
# работа, проверки, git add, git commit
git push -u origin feature/telegram-upload
```

Типы: `feature/*`, `fix/*`, `chore/*`; автоматизированные задачи могут иметь
префикс `codex/`, например `codex/feature/telegram-upload`.
Коммиты: `feat: …`, `fix: …`, `chore: …`, `docs: …`, `test: …`.
Одна ветка/PR — одна связная задача. Не коммитить в `preprod` и `main` напрямую.
Чтобы обновить ветку: `git fetch origin`, затем `git merge origin/preprod`.
Общие ветки не ребейзить и не force-push.

Feature PR → preprod: CI, ревью при наличии второго разработчика, **Squash and merge**.
Удалить feature-ветку после merge. На preprod проверить совместный сценарий фич.

## Релиз

1. На время проверки зафиксировать состав preprod: новые фичи не сливать.
2. Создать PR `preprod → main`, например `release: v0.1.0`.
3. Прогнать CI и smoke на preprod. Изменение preprod требует повторной проверки.
4. Слить через **Create a merge commit**. Для постоянных веток не использовать squash
   или rebase: иначе ломается общая история последующих релизов.
5. На полученном main создать annotated tag и запушить его:

```sh
git switch main
git pull --ff-only origin main
git tag -a v0.1.0 -m "LinkSift v0.1.0"
git push origin v0.1.0
```

6. PR `main → preprod`, тоже merge commit, чтобы синхронизировать историю.
7. Развёртывать проверенный commit/tag; автодеплой этим каркасом не включён.

Если на preprod есть неготовая фича — исправить/откатить её через PR и повторно
проверить интеграцию. Не переносить случайный набор коммитов напрямую в main.

## Hotfix и откат

Hotfix ответвляется от обновлённой main: `hotfix/описание`, проходит CI и PR в main.
После релиза обязательно PR main → preprod с merge commit. При откате использовать
revert PR, а не reset/force push. Откат merge-коммита требует выбора родителя (`-m 1`)
и понимания повторного релиза; изменения БД проверяются отдельно.

## Настройки GitHub — применить после первого push

Настройки ниже документированы, **не применены удалённо**:

- default branch: main;
- защитить main и preprod: PR обязателен, force push и удаление запрещены;
- обязательные CI checks: `quality` и `container`, после их первого успешного запуска;
- требовать актуальную ветку перед merge и закрытие обсуждений;
- при работе одному не требовать чужого approval; при появлении команды — минимум 1;
- разрешить merge commits и squash; не требовать linear history у main/preprod;
- не удалять постоянную preprod после релизного PR;
- production/preprod: разные боты, секреты, каталоги данных и процессы запуска.

Доступность branch protection для приватного репозитория зависит от тарифа GitHub.
[Официальная документация](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches).
