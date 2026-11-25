FROM ghcr.io/prefix-dev/pixi:0.84.2 AS build

WORKDIR /code
COPY . .
RUN pixi install --locked -e prod
RUN pixi shell-hook -e prod -s bash > /shell-hook
RUN printf '#!/bin/bash\n' > /entrypoint.sh && \
    cat /shell-hook >> /entrypoint.sh && \
    printf '\nexec "$@"\n' >> /entrypoint.sh && chmod +x /entrypoint.sh

FROM docker.io/library/ubuntu:24.04
ENV LANG=C.UTF-8 LC_ALL=C.UTF-8 HOME=/tmp PYTHONDONTWRITEBYTECODE=1
COPY --from=build /code/.pixi/envs/prod /code/.pixi/envs/prod
COPY --from=build /code/quetz /code/quetz
COPY --from=build /entrypoint.sh /entrypoint.sh
USER 10001:10001
WORKDIR /tmp
EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
CMD ["quetz", "start", "/quetz-deployment", "--host", "0.0.0.0", "--port", "8000"]
