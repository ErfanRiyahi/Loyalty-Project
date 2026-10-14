const tabs = ['Standard', 'CI', 'TS', 'DS', 'Cluster', 'Churn', 'Monthly'];
for (const name of tabs) {
 document.getElementById('tabBtn' + name).addEventListener('click', () => {
  for (const other of tabs) {
   document.getElementById('tabBtn' + other).classList.toggle('active', name === other);
   document.getElementById('tab' + other).classList.toggle('active', name === other);
  }
 });
}
